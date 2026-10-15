# Assignment 2 report · A plan RepoMind cannot quietly abandon

Every number here that has a field in `reports/LAB_02.json` goes there too: the
checker reads that file (format: `checks/FORMATS.md`, section 10.10). Give each
number its run count. Mark any vendor figure you cite with its source and the date
you read it.

## Part A · The plan artifact
Your `args` choice, `args_json` or one shape per tool with `oneOf`, and why, in two
sentences. Your strict-mode count, in two sentences: optional fields and union
types against the budgets of 24 and 16, and whether a strict request carrying the
schema was accepted (or that your vendor has no strict mode).

## Part B · The validator and the boundary

| Plan | Valid | Failures (step, check) |
|---|---|---|
| `good_export_fix.json` | | |
| `good_triage.json` | | |
| `s18_specimen.json` | | |

Your re-plan bound, `MAX_REPLANS`, and one line on why. How many of your planner's
plans, in your measured runs, broke the schema or did not end with `post_comment`
(your `schema` lines), out of how many plans.

## Part C · Revision at a checkpoint
The checkpoint's check, in one sentence, and your revision bound, `MAX_REVISIONS`.

## Part D · A second pass before posting
Your four external checks, one line each, and your bound, `MAX_ROUNDS`, in one
line. For each mode, `off`, `self` and `external`, which of slide 41's three gates
it passes: can a check find the error, does the critic know more than the agent,
is there a limit and a log?

## Part E · Detectors and the diff
How your diff matches a traced call to a plan step.

**The looping run.** Questions 1 to 3, each with the turns or steps that fired, and
how you answered question 2 without `depends_on`. Question 4, in one sentence.

**Slide 51's run.** Questions 1 to 3, each with the steps that fired. Question 4, in
one sentence. The diff's label for every step of the plan.

## Part F · What the plan and the second pass bought
Three sweeps a configuration: a pilot, not a settled difference.

| Measure | Agent | Planned, off | Planned, self | Planned, external |
|---|---|---|---|---|
| Passes, of 18 | | | | |
| Per issue, 4201 to 4206, of 3 each | | | | |
| Spread: the lowest and highest sweep, of 6 | | | | |
| Tokens per run | | | | |
| Latency per run: median, and slowest | | | | |
| Plan overhead: the mean share of prompt tokens, and how it changes with run length | | | | |
| Second-pass overhead: the mean share of prompt tokens | | | | |
| Runs with at least one exact repeat | | | | |
| `off_plan` lines | | | | |
| Revisions per run: mean, and maximum | | | | |
| Second-pass rounds per run: mean, and maximum | | | | |
| Drafts changed; of those fixed, and broken | | | | |
| Drafts held at the bound | | | | |

Leave a cell empty where a measure does not apply. The script that built this
table: its path, and the command that runs it.

1. **What did the plan buy RepoMind, concretely?** Artifacts and counts, not
   qualities.
2. **Where did it not pay?** Slide 52's four cases, applied to your six issues. On
   which would the plan cost more than the execution?
3. **What did each second pass buy, and what did it cost?** Which errors each mode
   caught, whether either turned a passing draft into a failing one, what each
   added in tokens and time, what happened to issue 4206 under each, and which of
   slide 41's three gates each mode passes.
4. **Which failure did no detector catch?** Did you see a run that reported success
   before the task was done, and how did you know?

## Part G · Note-taking against compaction
Your `COMPACT_AT`, and what your progress file holds.

| Run | Issue | Progress file shown | Compacted before the questions | Answers right, of 6 |
|---|---|---|---|---|
| | | | | |

1. **What did the progress file keep that compaction lost,** and what did the file
   cost in tokens?
2. **Which context operations did RepoMind need?** Structured note-taking,
   sub-agent isolation, just-in-time retrieval and compaction, in that order: for
   each, whether your longest run in Part F needed it, and what it would have cost.

## Assistance
Which AI tool, what it wrote, and what you checked.
