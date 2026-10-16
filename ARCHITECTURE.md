# ARCHITECTURE.md · RepoMind on the seven layers

For each layer: what does this job, and where is it enforced. Cite code as a file
path and line number joined by a colon, inside backticks; a checker opens every
reference (`checks/FORMATS.md`, section 8). A layer held only by a sentence in a
prompt (any file under `prompts/`) is **EMPTY**, and so is a layer nothing does
yet. Status is one of: present, partial (say what is missing), or **EMPTY**. Each
assignment brings this file up to date.

What each layer is for (Lecture 1, slides 40 to 42):

- **Model**: reasoning, choosing tools, generating text.
- **Harness**: runs the loop, builds each prompt, trims old history.
- **Tools**: where the system acts on the world.
- **Memory & State**: what survives a step, a session, a restart.
- **Control & Policy**: what the system may do, and when it must ask.
- **Observability**: a step-by-step record of what it did.
- **Evaluation**: measuring quality, before and after release.

The table below shows RepoMind as Assignment 2 leaves it. The Harness row now
cites the validator and the boundary. Every other row that Assignment 2 changed
says what was added. Assignment 1's references still hold.

| Layer | What does this job | Where it is enforced | Status |
|---|---|---|---|
| Model | The configured model, called only through the metered client | `harness/client.py:116` | present |
| Harness | Assignment 1's loop, with three bounds checked in code before every call. In the planned way, every plan is checked against the schema and the four checks before anything runs. A rejected plan is re-planned up to `MAX_REPLANS` times, then escalated with no tool call. The plan is logged before the first tool call. The boundary refuses any call that isn't the current step's tool. Revision happens only at the checkpoint after a search, and each version is validated before it is logged. | `agent/loop.py:38`, `agent/loop.py:41`, `agent/loop.py:44`, `agent/validator.py:38`, `ways/planned.py:188`, `ways/planned.py:192`, `ways/planned.py:182`, `ways/planned.py:171`, `ways/planned.py:164`, `ways/planned.py:316`, `ways/planned.py:317`, `ways/planned.py:418`, `ways/planned.py:466` | present |
| Tools | Four tools behind one registry (read_file arrived with Assignment 2's starter); post_comment stamps the run_id | `tools/__init__.py:52`, `harness/tracker.py:60` | present |
| Memory & State | The plan and each step's status live outside the model for the length of a run. Part G's notes way keeps a progress file outside the conversation, and compacts the history once it passes `COMPACT_AT`. Nothing a run learns carries over to a later run. | `ways/notes.py:96`, `ways/notes.py:112` | partial: within a run only |
| Control & Policy | The executor can run, retry or halt a step, but never add, drop or reorder one. The issue never reaches the planner or the reviser, and the reviser sees step results without their arguments. Each run posts at most one comment, only after the second pass's last round, and a draft that still fails is held. Nothing yet asks a person before the comment is posted. (Lecture 5's approval point would sit at the plan.) | `ways/planned.py:316`, `agent/plan.py:104`, `agent/plan.py:130`, `ways/planned.py:497`, `ways/planned.py:526` | partial: no human approval |
| Observability | One trace line per model call and per tool call. Every plan version, revision, refused call, critique round, compaction and question also gets its own line. On top of that: three detectors, and a diff of the plan against the trace. | `agent/loop.py:50`, `ways/planned.py:481`, `agent/detectors.py:55`, `agent/diff.py:86` | partial: traces and detectors, no alerts |
| Evaluation | The grounded check compares the tracker against the answer key, and never reads the agent's own account. The external second pass checks each draft in code, against the repository and the run's own record, before it is posted. | `eval/check_triage.py:7`, `agent/critique.py:77` | partial: the grounded check is offline, and the run-time check covers form, not whether the cause is right |

**Empty layers: 0 of 7**, and four are partial. Assignment 2 moved Memory & State
and Control & Policy from empty to partial. It added state that lasts for one run,
and a boundary in code. There is still no memory across runs, and no person in the
loop.
