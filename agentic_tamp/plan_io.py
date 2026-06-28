"""Parse an agent-produced plan (JSON) into a unified-planning SequentialPlan.

Expected JSON format (written by the agent to ``plan.json``)::

    {
      "plan": [
        {"action": "move", "args": ["r1", "s", "b0"]},
        {"action": "open", "args": ["r1", "d0", "b0", "c0", "o0"]},
        {"action": "move", "args": ["r1", "b0", "g"]}
      ]
    }
"""

import json
from pathlib import Path

from unified_planning.plans import ActionInstance, SequentialPlan

PLAN_FORMAT_DOC = (
    'Write your plan to `plan.json` as: {"plan": [{"action": "<name>", '
    '"args": ["<obj1>", "<obj2>", ...]}, ...]}. Use the exact action names '
    "and object names from the problem description, in grounding order."
)


class PlanParseError(ValueError):
    """Raised when the agent's plan cannot be turned into a SequentialPlan."""


def parse_plan_obj(data: object, problem) -> SequentialPlan:
    """Convert a decoded JSON object into a SequentialPlan against ``problem``."""
    if not isinstance(data, dict) or "plan" not in data:
        raise PlanParseError(
            'Top-level JSON must be an object with a "plan" key holding a list '
            "of steps."
        )
    steps = data["plan"]
    if not isinstance(steps, list):
        raise PlanParseError('"plan" must be a list of {action, args} steps.')

    action_instances = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or "action" not in step or "args" not in step:
            raise PlanParseError(
                f"Step {i} must be an object with 'action' and 'args'. Got: {step!r}"
            )
        name = step["action"]
        args = step["args"]
        try:
            action = problem.action(name)
        except Exception as exc:  # noqa: BLE001 - surface a clear message to the agent
            raise PlanParseError(
                f"Step {i}: unknown action '{name}'. Available actions: "
                f"{[a.name for a in problem.actions]}."
            ) from exc
        if not isinstance(args, list):
            raise PlanParseError(f"Step {i}: 'args' must be a list, got {args!r}.")
        expected = len(action.parameters)
        if len(args) != expected:
            raise PlanParseError(
                f"Step {i}: action '{name}' expects {expected} args "
                f"({[p.name for p in action.parameters]}), got {len(args)}: {args}."
            )
        objs = []
        for arg in args:
            try:
                objs.append(problem.object(arg))
            except Exception as exc:  # noqa: BLE001
                raise PlanParseError(
                    f"Step {i}: unknown object '{arg}' for action '{name}'."
                ) from exc
        action_instances.append(ActionInstance(action, tuple(objs)))

    return SequentialPlan(action_instances)


def parse_plan_file(path: Path, problem) -> SequentialPlan:
    """Read and parse a ``plan.json`` file into a SequentialPlan."""
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise PlanParseError(f"plan.json is not valid JSON: {exc}") from exc
    return parse_plan_obj(data, problem)
