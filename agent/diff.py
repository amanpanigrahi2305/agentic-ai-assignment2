"""Assignment 2, Part E: the diff of the plan against what ran. This file is yours.

"The one people skip" (Lecture 2, slide 54). The checker calls it on slide 51's run
in fixtures/traces/s49/, so keep this exact signature (checks/FORMATS.md, section
10.2):

    diff(plan, trace) -> {"steps": {step_id: label}, "extra": [step numbers]}

    steps   every plan step, labelled
              executed   it ran, in plan order
              skipped    it never ran
              reordered  it ran, out of plan order
    extra   the step numbers of tool_call lines that match no plan step

How a call matches a step is yours to decide: by its tool, and by any arguments
the plan fixes (an argument written "$fill" is fixed by nothing). Say how in your
report. Mind slide 51's run: it calls run_tests twice, and only one of those calls
can belong to each run_tests step.

How this one matches, in order:
  1. A tool_call line that names its plan_step (the planned way's executor passes
     it) belongs to that step, if the step calls that tool.
  2. Otherwise the call goes to the first step in plan order that is still
     unmatched, calls the same tool, and whose fixed arguments all equal the
     call's (a "$fill" argument is fixed by nothing, so it matches any value).
  3. Each step takes at most one call; a call no step takes is extra.
Order: the matched steps whose calls ran in plan order are the longest run of
steps whose calls increase; any other matched step is reordered.
"""

from __future__ import annotations

import json

from harness.formats import FILL


def step_args(step: dict) -> dict:
    """A step's arguments, written as an object (args) or a JSON string (args_json)."""
    args = step.get("args")
    if args is None and isinstance(step.get("args_json"), str):
        try:
            args = json.loads(step["args_json"])
        except json.JSONDecodeError:
            args = {}
    return args if isinstance(args, dict) else {}


def _fits(step: dict, call: dict) -> bool:
    if not step.get("tool") or step.get("tool") != call.get("name"):
        return False
    given = call.get("input") or {}
    return all(given.get(k) == v for k, v in step_args(step).items() if v != FILL)


def match(plan: dict, trace: list[dict]) -> tuple[dict, list[int]]:
    """{step id as text: index of its tool_call line among the run's tool calls}, and the
    tool_call indices no step took."""
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    calls = [r for r in trace if r.get("type") == "tool_call"]
    taken: dict[str, int] = {}
    unmatched: list[int] = []
    for n, call in enumerate(calls):
        pick = None
        if call.get("plan_step") is not None:
            pick = next((s for s in steps if str(s.get("id")) == str(call["plan_step"])
                         and s.get("tool") == call.get("name") and str(s.get("id")) not in taken), None)
        if pick is None and call.get("plan_step") is None:
            pick = next((s for s in steps if str(s.get("id")) not in taken and _fits(s, call)), None)
        if pick is None:
            unmatched.append(n)
        else:
            taken[str(pick.get("id"))] = n
    return taken, unmatched


def _in_order(sequence: list[int]) -> set[int]:
    """Positions in `sequence` on its longest strictly increasing run (earliest positions win ties)."""
    best: list[list[int]] = []
    for i, value in enumerate(sequence):
        chain = max((c for c in best if sequence[c[-1]] < value), key=len, default=[])
        best.append(chain + [i])
    return set(max(best, key=len, default=[]))


def diff(plan: dict, trace: list[dict]) -> dict:
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    calls = [r for r in trace if r.get("type") == "tool_call"]
    taken, unmatched = match(plan, trace)
    ran = [s for s in steps if str(s.get("id")) in taken]
    keep = _in_order([taken[str(s.get("id"))] for s in ran])
    in_order = {str(s.get("id")) for i, s in enumerate(ran) if i in keep}
    labels = {}
    for s in steps:
        key = str(s.get("id"))
        labels[s.get("id")] = ("skipped" if key not in taken else "executed" if key in in_order else "reordered")
    return {"steps": labels, "extra": [calls[n].get("step") for n in unmatched]}
