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
"""

from __future__ import annotations


def repeat_check(trace: list[dict]) -> list[list]:
    raise NotImplementedError("Assignment 2 Part E: the repeat check")


def orphan_check(plan: dict) -> list:
    raise NotImplementedError("Assignment 2 Part E: the orphan check")


def expected_result_check(plan: dict, trace: list[dict]) -> list:
    raise NotImplementedError("Assignment 2 Part E: the expected-result check")


def ladder(plan: dict, trace: list[dict]) -> dict:
    raise NotImplementedError("Assignment 2 Part E: questions 1 to 3")


if __name__ == "__main__":
    raise SystemExit("Assignment 2 Part E: print both runs' ladders here, if you like")
