"""Assignment 2, Part E: three detectors, and Lecture 2's ladder. This file is yours.

Three of the four plan failures have a detector of a few lines over a trace
(Lecture 2, slides 45 to 49); the validator is the fourth. The checker calls these
on fixtures/traces/, so keep these exact signatures (checks/FORMATS.md, section
10.2):

    repeat_check(trace) -> list[list]
        Circular reasoning. Exact repeats: two tool_call lines with the same tool
        and the same arguments. Returns each group of repeats as the step numbers
        of its tool_call lines, e.g. [[1, 3], [2, 4]].

    orphan_check(plan) -> list
        Hallucinated steps. The ids of steps, other than the last, whose result no
        later step uses: no later step lists them in depends_on.

    expected_result_check(plan, trace) -> list
        Premature stopping, in part. The ids of plan steps that did not run and
        return their result. It catches skipped steps, not a plan too short.

    ladder(plan, trace) -> {"q1": {"fired": bool, "ids": [...]}, "q2": ..., "q3": ...}
        Lecture 2's questions 1 to 3 (slide 50), in order: did any two steps do
        the same thing; is any step's result never used; did every planned step
        execute. "ids" says what fired: groups of step numbers for q1, step ids
        (or, from a trace, step numbers) for q2 and q3. Question 4 needs
        judgment, so it goes in your report, not here.

    plan    a plan (section 10.1)
    trace   a list of trace lines, as harness.trace.read_trace returns them

A plan with no depends_on cannot answer question 2 from the plan. Answer it from
the trace, and say how in your report.

How question 2 is answered from a trace (unused_results): a call's result counts
as used only when a later call acts on something it returned. The evidence is a
later call's input naming a path the result listed, or, for a search, the next
read of a file whose name contains the search's term (the trace may record a
count, "247 results", rather than the paths). A result with no such evidence is
flagged as never used.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

from agent.diff import match


def _tool_calls(trace: list[dict]) -> list[dict]:
    return [r for r in trace if r.get("type") == "tool_call"]


def repeat_check(trace: list[dict]) -> list[list]:
    groups: dict[str, list] = {}
    for call in _tool_calls(trace):
        key = json.dumps([call.get("name"), call.get("input") or {}], sort_keys=True)
        groups.setdefault(key, []).append(call.get("step"))
    return [steps for steps in groups.values() if len(steps) > 1]


def orphan_check(plan: dict) -> list:
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    orphans = []
    for i, step in enumerate(steps[:-1]):
        used = any(str(step.get("id")) in {str(d) for d in later.get("depends_on") or []} for later in steps[i + 1:])
        if not used:
            orphans.append(step.get("id"))
    return orphans


def expected_result_check(plan: dict, trace: list[dict]) -> list:
    calls = _tool_calls(trace)
    taken, _ = match(plan, trace)
    missing = []
    for step in plan.get("steps") or []:
        n = taken.get(str(step.get("id")))
        if n is None or calls[n].get("is_error"):
            missing.append(step.get("id"))
    return missing


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def unused_results(trace: list[dict]) -> list:
    """Question 2 from a trace alone: the step numbers of tool calls no later call shows it used."""
    calls = _tool_calls(trace)
    used = set()
    for later_n, later in enumerate(calls):
        named = {str(v) for v in (later.get("input") or {}).values() if isinstance(v, str)}
        for n, earlier in enumerate(calls[:later_n]):
            listed = set(earlier.get("paths") or []) | set(re.findall(r"[\w./-]+\.\w+", earlier.get("result_excerpt") or ""))
            if named & listed:
                used.add(n)

        for value in named:
            stem = _squash(PurePosixPath(value).stem)
            searches = [n for n, c in enumerate(calls[:later_n])
                        if (c.get("input") or {}).get("query") and _squash(c["input"]["query"]) in stem]
            if stem and searches and "." in value:
                used.add(searches[-1])
    return [c.get("step") for n, c in enumerate(calls) if n not in used]


def ladder(plan: dict, trace: list[dict]) -> dict:
    repeats = repeat_check(trace)
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    if any("depends_on" in s for s in steps):
        orphans = orphan_check(plan)
    else:  
        orphans = unused_results(trace)
    skipped = expected_result_check(plan, trace)
    return {
        "q1": {"fired": bool(repeats), "ids": repeats},
        "q2": {"fired": bool(orphans), "ids": orphans},
        "q3": {"fired": bool(skipped), "ids": skipped},
    }


if __name__ == "__main__":
    from agent.diff import diff
    from harness import ROOT
    from harness.trace import read_trace

    for run in ("looping", "s49"):
        folder = ROOT / "fixtures" / "traces" / run
        plan, trace = json.loads((folder / "plan.json").read_text()), read_trace(folder / "trace.jsonl")
        print(run, json.dumps(ladder(plan, trace)))
        print(run, "diff", json.dumps(diff(plan, trace)))
