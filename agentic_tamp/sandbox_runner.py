"""Run a Claude agent in robocode's Docker sandbox (adapted, self-contained).

This reuses the ``robocode-sandbox`` image and the sandboxing approach from
``~/robocode`` (network firewall, write-restricted ``/sandbox`` bind-mount,
macOS-Keychain OAuth forwarding, stream-json parsing) but drops robocode's
``prpl-mono`` bind-mount and primitive scaffolding, which are specific to that
project. One ``run_agent`` call is one batch invocation of the ``claude`` CLI.
"""

import json
import logging
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_IMAGE = "robocode-sandbox"

_RATE_LIMIT_RE = re.compile(
    r"out of extra usage.*resets\s+(\d{1,2}(?:am|pm))", re.IGNORECASE
)

_VALIDATE_SANDBOX_SCRIPT = """\
#!/usr/bin/env python3
import json
import os
import sys

data = json.load(sys.stdin)
tool_name = data.get("tool_name", "")
tool_input = data.get("tool_input", {})

if tool_name not in ("Write", "Edit"):
    sys.exit(0)

file_path = tool_input.get("file_path", "")
if not file_path:
    sys.exit(0)

sandbox = os.path.realpath(os.getcwd())
resolved = os.path.realpath(file_path)

if resolved == sandbox or resolved.startswith(sandbox + os.sep):
    sys.exit(0)

json.dump({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"Blocked: {file_path} resolves outside the sandbox directory"
        ),
    }
}, sys.stdout)
"""

_SANDBOX_SETTINGS = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Write|Edit",
                "hooks": [
                    {
                        "type": "command",
                        "command": "python3 .claude/validate_sandbox.py",
                    }
                ],
            }
        ]
    }
}


@dataclass
class AgentRunResult:
    success: bool
    output_file: Path | None
    error: str | None
    total_cost_usd: float | None = None
    num_turns: int = 0
    rate_limit_reset: str | None = None


def _get_claude_oauth_token() -> str | None:
    """Extract the Claude Code OAuth token from the macOS Keychain (darwin only)."""
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                "Claude Code-credentials",
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return None
        creds = json.loads(result.stdout.strip())
        return creds.get("claudeAiOauth", {}).get("accessToken")
    except (subprocess.SubprocessError, json.JSONDecodeError, KeyError):
        return None


def setup_sandbox(sandbox_dir: Path, claude_md: str) -> None:
    """Create the sandbox dir, git-init it, and install the write-guard hook."""
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    if not (sandbox_dir / ".git" / "HEAD").exists():
        subprocess.run(
            ["git", "init"], cwd=str(sandbox_dir), check=True, capture_output=True
        )
    claude_dir = sandbox_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)
    (claude_dir / "settings.json").write_text(json.dumps(_SANDBOX_SETTINGS, indent=2))
    (claude_dir / "validate_sandbox.py").write_text(_VALIDATE_SANDBOX_SCRIPT)
    (sandbox_dir / "CLAUDE.md").write_text(claude_md)


def _build_claude_args(
    prompt: str, model: str, system_prompt: str, max_budget_usd: float, tools: str
) -> list[str]:
    args = [
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--tools",
        tools,
        "--setting-sources",
        "project",
    ]
    if system_prompt:
        args += ["--system-prompt", system_prompt]
    if max_budget_usd > 0:
        args += ["--max-budget-usd", str(max_budget_usd)]
    return args


def _parse_stream(proc: "subprocess.Popen[str]", log_file) -> tuple:
    """Parse stream-json stdout; log assistant/tool events; return summary."""
    is_error = False
    error_text: str | None = None
    num_turns = 0
    total_cost: float | None = None
    rate_limit_reset: str | None = None

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mtype = msg.get("type", "")
        if mtype == "assistant":
            for block in msg.get("message", {}).get("content", []):
                bt = block.get("type")
                if bt == "text":
                    text = block["text"]
                    log_file.write(f"[agent] {text}\n")
                    m = _RATE_LIMIT_RE.search(text)
                    if m:
                        rate_limit_reset = m.group(1)
                elif bt == "tool_use":
                    inp = json.dumps(block.get("input", {}))
                    if len(inp) > 300:
                        inp = inp[:300] + "..."
                    log_file.write(f"[tool] {block.get('name')}({inp})\n")
        elif mtype == "tool_result":
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 500:
                content = content[:500] + "..."
            log_file.write(f"[result] {content}\n")
        elif mtype == "result":
            is_error = msg.get("is_error", False)
            num_turns = msg.get("num_turns", 0)
            total_cost = msg.get("total_cost_usd")
            if is_error:
                error_text = msg.get("result", "Unknown error")
                if not rate_limit_reset:
                    m = _RATE_LIMIT_RE.search(error_text or "")
                    if m:
                        rate_limit_reset = m.group(1)
        log_file.flush()

    proc.wait()
    assert proc.stderr is not None
    stderr_output = proc.stderr.read()
    if proc.returncode != 0 and not is_error:
        is_error = True
        error_text = (
            stderr_output[:1000]
            if stderr_output
            else f"Process exited with code {proc.returncode}"
        )
    if rate_limit_reset and not is_error:
        is_error = True
        error_text = f"Rate-limited: resets {rate_limit_reset}"
    return is_error, error_text, num_turns, total_cost, rate_limit_reset


def run_agent(
    sandbox_dir: Path,
    prompt: str,
    *,
    model: str,
    output_filename: str,
    system_prompt: str = "",
    max_budget_usd: float = 5.0,
    image: str = DEFAULT_IMAGE,
    tools: str = "Bash,Read,Write,Edit,Glob,Grep",
    log_path: Path | None = None,
) -> AgentRunResult:
    """Launch the ``claude`` CLI inside the sandbox container and collect output."""
    sandbox_abs = str(sandbox_dir.resolve())
    container_name = f"agentic-tamp-{uuid.uuid4().hex[:8]}"

    oauth_token = _get_claude_oauth_token()
    if not oauth_token:
        logger.warning(
            "No Claude OAuth token in Keychain; bind-mounting ~/.claude. "
            "Run `claude login` on the host if auth fails."
        )
    host_claude_cfg = Path(
        os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))
    )

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--cap-add=NET_ADMIN",
        "--cap-add=NET_RAW",
        "-e",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000",
    ]
    if oauth_token:
        docker_cmd += ["-e", "CLAUDE_CODE_OAUTH_TOKEN"]
    else:
        docker_cmd += ["-v", f"{host_claude_cfg}:/home/node/.claude"]
    docker_cmd += ["-v", f"{sandbox_abs}:/sandbox", "-w", "/sandbox", image]
    docker_cmd += _build_claude_args(
        prompt, model, system_prompt, max_budget_usd, tools
    )

    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE")}
    env.setdefault("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "128000")
    if oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token

    logger.info("Starting sandbox container=%s image=%s", container_name, image)
    log_path = log_path or (sandbox_dir / "agent_log.txt")
    with open(log_path, "a") as log_file:
        log_file.write(f"\n===== run model={model} =====\n")
        proc = subprocess.Popen(  # noqa: S603
            docker_cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        is_error, error_text, num_turns, total_cost, rate_limit_reset = _parse_stream(
            proc, log_file
        )

    if is_error:
        return AgentRunResult(
            success=False,
            output_file=None,
            error=error_text,
            total_cost_usd=total_cost,
            num_turns=num_turns,
            rate_limit_reset=rate_limit_reset,
        )

    output_path = sandbox_dir / output_filename
    if output_path.exists():
        return AgentRunResult(
            success=True,
            output_file=output_path,
            error=None,
            total_cost_usd=total_cost,
            num_turns=num_turns,
        )
    return AgentRunResult(
        success=False,
        output_file=None,
        error=f"Agent did not write {output_filename}",
        total_cost_usd=total_cost,
        num_turns=num_turns,
    )
