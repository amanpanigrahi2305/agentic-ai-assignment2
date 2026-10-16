"""Assignment 2, Parts A and C: the planner and the reviser. This file is yours.

The contract (checks/FORMATS.md, section 10). The checker calls both functions
directly, with a scripted model that keeps a copy of every request, so keep these
exact signatures. You may add keyword arguments with defaults; the checker passes
only these.

    make_plan(client, issue_number, tool_schemas, trace=None) -> dict
    revise_plan(client, plan, step_results, trace=None) -> dict

    client        harness.client.ModelClient: client.create(system=, messages=, tools=)
    issue_number  the issue to triage, an int
    tool_schemas  the tool definitions, as ctx.tools.schemas gives them
    plan          the active plan, its steps' statuses brought up to date
    step_results  one entry per step that has run (section 10.3)
    trace         a harness.trace.TraceWriter, or None. When you get one, trace your
                  model call: trace.model_call(0, response, purpose="plan") in
                  make_plan, purpose="revise" in revise_plan
    returns       a plan (section 10.1): {"meta": {...}, "steps": [...]}

make_plan writes the plan and stops (Lecture 2, slide 15). Its request carries the
task, the issue number and the tool list, and nothing from the issue: not its body,
not its title. The checker looks for each issue's sentinel string in every request.
The usual way to get the plan back as data: offer the model one tool whose
input_schema is agent/plan_schema.json, and read the plan from its call. Mark an
argument that waits on an earlier step's result "$fill"; the executor fills it in.

revise_plan repairs before it replaces: it never changes a step whose status is
done; it may change a step that failed, to retry it, and any step not yet run. A
step whose step result says "done" comes back unchanged, every field but status,
whatever the model wrote. Its request carries structured step results only (status, counts, paths,
error codes): never the issue's text, and never a step result's `args`, which the
executor may have filled in from the issue.

Keep your prompts in prompts/.

What a returned plan looks like when the model wrote no plan (it answered in prose):
its steps are [] and meta.error says so. ways/planned.py rejects it like any plan
that breaks the schema.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "agent" / "plan_schema.json"
PLANNER_PROMPT = "prompts/planner.md"
REVISER_PROMPT = "prompts/reviser.md"
PLAN_TOOL = "submit_plan"


RESULT_FIELDS = ("id", "tool", "status", "count", "paths", "error_code")


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def plan_tool() -> dict:
    """The one tool the planner and the reviser are offered: its input is a plan."""
    return {"name": PLAN_TOOL, "description": "Submit the whole plan, every step, in the order the steps run.",
            "input_schema": load_schema(), "strict": True}


def describe_tools(tool_schemas: list[dict]) -> str:
    """The tool list as the planner reads it: each tool's name, purpose and arguments."""
    lines = []
    for tool in tool_schemas:
        schema = tool.get("input_schema") or {}
        required = set(schema.get("required") or [])
        args = ", ".join(f"{name} ({prop.get('type', 'any')}{'' if name in required else ', optional'}: "
                         f"{prop.get('description', '')})"
                         for name, prop in (schema.get("properties") or {}).items())
        lines.append(f"- {tool['name']}: {tool.get('description', '')} Arguments: {args or 'none'}.")
    return "\n".join(lines)


def _plan_body(response) -> dict | None:
    """The plan the model submitted through its plan tool, or None if it wrote prose."""
    for call in response.tool_calls:
        if call.name == PLAN_TOOL:
            return copy.deepcopy(call.input)
    return None


def _as_plan(response, prompt: str, tools: list[str]) -> dict:
    body = _plan_body(response)
    meta = {"model": response.model, "prompt": prompt, "tools": list(tools)}
    if body is None:
        meta["error"] = f"no plan: the model answered without calling {PLAN_TOOL}"
        return {"meta": meta, "steps": []}
    body.pop("meta", None)
    return {"meta": meta, **body}


def make_plan(client, issue_number: int, tool_schemas: list[dict], trace=None, feedback: str | None = None) -> dict:
    """feedback: why the previous plan was rejected, for a re-plan. It names steps and
    checks, never anything from the issue, which the planner never sees."""
    names = [t["name"] for t in tool_schemas]
    request = (f"Plan the triage of issue #{issue_number}.\n\n"
               f"The tools the plan may use:\n{describe_tools(tool_schemas)}")
    if feedback:
        request += f"\n\nYour previous plan was rejected, for these reasons. Write a plan without them:\n{feedback}"
    response = client.create(system=(ROOT / PLANNER_PROMPT).read_text(),
                             messages=[{"role": "user", "content": request}], tools=[plan_tool()])
    if trace is not None:
        trace.model_call(0, response, purpose="plan")
    return _as_plan(response, PLANNER_PROMPT, names)


def _key(step: dict) -> str:
    return str(step.get("id"))


def _without_status(step: dict) -> dict:
    return {k: v for k, v in step.items() if k != "status"}


def revise_plan(client, plan: dict, step_results: list[dict], trace=None, reason: str | None = None,
                feedback: str | None = None, tool_schemas: list[dict] | None = None) -> dict:
    """reason: why the checkpoint's check failed, written by code from the step results
    (never a search term). feedback: why an earlier revision was rejected. tool_schemas:
    the tool definitions, so the reviser writes each tool's own arguments (without them,
    it gets the plan's tool names alone)."""
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    results = [{k: r.get(k) for k in RESULT_FIELDS} for r in step_results]
    shown = {k: v for k, v in plan.items() if k != "meta"}
    tools = (describe_tools(tool_schemas) if tool_schemas
             else ", ".join((plan.get("meta") or {}).get("tools") or []))
    request = (f"The check that failed: {reason or 'the checkpoint after the search'}\n\n"
               f"The tools the plan may use, and their only arguments:\n{tools}\n\n"
               f"The plan as it stands:\n{json.dumps(shown, indent=1)}\n\n"
               f"What each step that ran returned:\n{json.dumps(results, indent=1)}")
    if feedback:
        request += f"\n\nYour previous revision was rejected, for these reasons:\n{feedback}"
    response = client.create(system=(ROOT / REVISER_PROMPT).read_text(),
                             messages=[{"role": "user", "content": request}], tools=[plan_tool()])
    if trace is not None:
        trace.model_call(0, response, purpose="revise")
    revised = _as_plan(response, REVISER_PROMPT, (plan.get("meta") or {}).get("tools") or [])
    if (revised["meta"]).get("error"):
        return revised

    done = {_key(r) for r in step_results if r.get("status") == "done"} | {_key(s) for s in steps
                                                                         if s.get("status") == "done"}
    kept = [copy.deepcopy(s) for s in steps if _key(s) in done]
    rest = [s for s in revised.get("steps") or [] if not (isinstance(s, dict) and _key(s) in done)]
    revised["steps"] = kept + rest
    return revised
