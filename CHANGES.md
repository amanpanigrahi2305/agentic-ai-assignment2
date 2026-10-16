# CHANGES.md

Three lines per assignment: what it added, what it removed, what it constrained.
Removals are logged like additions.

## Assignment 1
- **Added:** a bounded tool loop; four ways to triage an issue (a direct call, a workflow, an agent, and a hybrid of the two); a grounded success check that reads the tracker; a results script
- **Removed:** nothing
- **Constrained:** every agent run to three bounds checked in code (steps, tokens, wall clock); success to what the tracker holds for the run's ID

## Assignment 2
- **Added:** a plan artifact, defined by `agent/plan_schema.json` and written by a planner that never sees the issue; a validator (the schema, a final `post_comment` step and four checks), where a rejected plan is re-planned, then escalated; a revision checkpoint after the first search; a second pass with three modes (`off`, `self` and `external`); three detectors, and a diff of the plan against the trace; a progress file and compaction (the notes way); and a script that builds the results from the traces (`eval/lab02.py`)
- **Removed:** nothing
- **Constrained:** the executor, to the active plan (it can run, retry or halt a step, but never add, drop or reorder one; an off-plan call is refused and logged, and an exact repeat is refused); revision, to one checkpoint and `MAX_REVISIONS`; the reviser, to step results without their arguments; and the comment, to one post after the second pass's last round, with a draft that still fails at `MAX_ROUNDS` held, not posted
