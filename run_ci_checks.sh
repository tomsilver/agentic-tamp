#!/bin/bash
# Fast local checks for agentic-tamp: lint (if ruff present), byte-compile,
# and import every module to catch obvious breakage.
set -e
cd "$(dirname "$0")"
source .venv/bin/activate

if command -v ruff >/dev/null 2>&1; then
    echo "== ruff =="
    ruff check agentic_tamp || true
fi

echo "== py_compile =="
python -m py_compile agentic_tamp/*.py

echo "== import smoke =="
python - <<'PY'
import importlib
for m in [
    "agentic_tamp.instances",
    "agentic_tamp.serialize",
    "agentic_tamp.plan_io",
    "agentic_tamp.validate",
    "agentic_tamp.baseline",
    "agentic_tamp.sandbox_runner",
    "agentic_tamp.prompts",
    "agentic_tamp.agent_solver",
    "agentic_tamp.compare",
]:
    importlib.import_module(m)
print("all modules import OK")
PY
echo "OK"
