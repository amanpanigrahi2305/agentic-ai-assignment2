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
"""

from __future__ import annotations


def diff(plan: dict, trace: list[dict]) -> dict:
    raise NotImplementedError("Assignment 2 Part E: the diff")
