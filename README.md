# RepoMind

The course's running system, built one layer at a time. RepoMind triages issues
for **Ledgerline**, a small reporting and export service: it reads an issue,
searches Ledgerline's private codebase, and posts a triage comment where the
issue's author can read it.

That combination is deliberate. RepoMind reads text anyone can write, reaches
code nobody outside the team should see, and writes somewhere public. Lecture 1
calls it the lethal trifecta. You build it this way on purpose, and Lecture 8 is
when you close it.

## Start here

You have two things: this repository, and the assignment handout from your
instructor. The handout says what to build and how it is graded; this file says
how the repository works. For Assignment 2, read the handout's "Getting started"
first.

This repository holds Assignment 1's working solution in place of your own code:
the bounded loop, the four ways, the grounded check and the results script. Your
Assignment 1 repository stays as it is. Assignment 2's new files are stubs that
raise `NotImplementedError` until you fill them in, so the planned way does not
run on a fresh copy. That is expected.

### What you need

- Python 3.10 or later, `git` and `make`.
- The model and API key you used in Assignment 1. Never commit the key and never
  share it.

### Set up, and use your Assignment 1 model

```bash
make setup                     # creates .venv and installs the three dependencies
source .venv/bin/activate      # in every new terminal
make test                      # the harness's own tests; they spend no tokens
```

From your Assignment 1 repository, copy the `provider`, `model`, `base_url` and
`api_key_env` lines of `settings.yaml` into this one, and your model's line in
`pricing.yaml`, if this sheet does not have it. Change nothing else in
`settings.yaml`. Any vendor's model with tool calling works, but Part F reruns
Assignment 1's agent, and on the same model its runs can be read beside the ones
you measured there. Two backends cover almost every vendor:

| Your model | In `settings.yaml` |
|---|---|
| Claude, through Anthropic's API | `provider: anthropic`, `model`; the key in `ANTHROPIC_API_KEY` |
| Anything with an OpenAI-compatible API: OpenAI, Google Gemini, Mistral, DeepSeek, Groq, OpenRouter, a local Ollama or vLLM server, and many more | `provider: openai-compatible`, `model`, `base_url` (none for OpenAI itself), and `api_key_env`, the variable that holds your key (default `OPENAI_API_KEY`) |

Then check it with two tiny calls:

```bash
export OPENAI_API_KEY=...      # or the variable your api_key_env names
make ping                      # your key, your model, its tool calling and its price line
```

If the `export` line is already in your shell profile, skip it. `make test` and
`make ping` must both pass before you write any code. Your code never depends on
the vendor: the harness keeps every message in one format and translates for the
backend. A tool definition marked `"strict": true` goes to your vendor as its
strict mode, if it has one.

### Where to start: Assignment 2

| Order | What you write | How you test it | Costs |
|---|---|---|---|
| Part A | `agent/plan_schema.json`, `make_plan` in `agent/plan.py`, its prompt, and the planning step of `ways/planned.py` | A few planner calls on the development issues | A few calls |
| Part B | `agent/validator.py`; `ways/planned.py` with its reject exit and its boundary | `validate` on `fixtures/plans/`, free; the scripted models, free; then `python run.py --way planned --set dev` | Tokens, for the dev runs |
| Part C | `revise_plan` in `agent/plan.py` and its prompt; the checkpoint after the first search in `ways/planned.py` | `python run.py --way planned --set dev` | Tokens |
| Part D | `verify` and `self_critique` in `agent/critique.py`, their prompts, and the second pass with `MAX_ROUNDS` in `ways/planned.py` | The `DraftNames…` scripted models, free; then `python run.py --way planned --critique self --set dev`, and `external` | Tokens |
| Part E | `agent/detectors.py`, `agent/diff.py` | Your detectors over `fixtures/traces/` | Nothing |
| Part F | The 72 measured runs, and a script in `eval/` that builds the table | `make reset`, then the runs, then `make check-02` | Most of the spend |
| Part G | `ways/notes.py`: a progress file, a compaction, six questions | `ScriptedTriage`, free; then the 12 runs | Tokens |

Part E can be done at any point. `make check-02` works at any point and shows what
is still missing; it is the same checker staff run.

## What is here, and what is yours

| Path | What it is | Yours to edit? |
|---|---|---|
| `harness/` | The model client, tracker, trace writer, runner, prices, scripted models. New for Assignment 2: `harness/schema.py`, which checks a plan against your schema; `trace.plan`; `trace.event`, for the `off_plan`, `revision`, `critique`, `compaction`, `question` and `schema` lines; `purpose=` on `trace.model_call`; the files each tool call returned (`paths`); the `escalated` ending; `ctx.critique`, `ctx.notes` and `ctx.progress_path`; and the scripted models in `harness/scripted.py` | No |
| `tools/` | Four tools and their registry: `read_issue`, `search_repo`, `read_file` (new, bare) and `post_comment` | No (Assignment 3 rewrites all four) |
| `fixtures/issues/`, `fixtures/repo/`, `fixtures/answers.yaml` | The same six evaluation and two development issues, Ledgerline's codebase, and the answers. Each issue body now ends with a sentinel string | **Never** |
| `fixtures/plans/` | Plans to validate, among them slide 18's five-step specimen | **Never** |
| `fixtures/traces/` | Two runs to diagnose, each a plan and its trace: `looping/`, and `s49/`, slide 51's export-bug run | **Never** |
| `checks/` | `check_02.py`, the Assignment 2 checker, and `FORMATS.md`, which defines every format it reads (section 10 is new) | No |
| `tests/` | The harness's own tests | No |
| `settings.yaml`, `pricing.yaml` | Your model, the ceilings, the dated price sheet | Once, in setup: your model and its price line; never the ceilings |
| `run.py` | Runs a way over a set of issues, one trace per run | No |
| `agent/loop.py`, `agent/bounds.yaml` | Assignment 1's bounded loop and its bounds | Reuse them |
| `agent/plan.py`, `agent/validator.py`, `agent/critique.py`, `agent/detectors.py`, `agent/diff.py` | Assignment 2's stubs: the planner and reviser, the four checks, the second pass's two critics, the detectors, the diff | **Yes** |
| `agent/plan_schema.json` | Your plan schema, which you create in Part A | **Yes** |
| `ways/direct.py`, `ways/workflow.py`, `ways/agent.py`, `ways/hybrid.py`, `ways/common.py` | Assignment 1's four ways | Reuse them. Leave `ways/agent.py` and `prompts/agent.md` as they are: Part F measures against them |
| `ways/planned.py` | RepoMind with a plan: plan, validate, execute, revise, and the second pass before posting | **Yes** |
| `ways/notes.py` | Part G: the planned way with a progress file and a compaction, and six questions | **Yes** |
| `eval/` | Assignment 1's grounded check (`check_triage.py`), Part 0 script and results script; your Part F table script | **Yes**: extend `summarize.py`, or add your own |
| `prompts/` | Assignment 1's prompts, and every prompt you write, one file each | **Yes** |
| `reports/`, `ARCHITECTURE.md`, `CHANGES.md` | Your write-ups; `reports/` starts with the templates for `LAB_02.md` and `LAB_02.json` | **Yes** |
| `runs/`, `tracker/` | Made by your first run: traces, the run ledger, posted comments | Written by the harness; **commit them** |

The stubs say what each function receives and returns, and `checks/FORMATS.md`,
section 10, fixes every format: the plan, its trace lines, `step_results`, the
second pass's rounds, the progress file, and each field of `reports/LAB_02.json`.

## Running

```bash
python run.py --way planned --set dev                    # your planned way on the two dev issues
python run.py --way planned --critique self --set dev    # with the second pass: off (the default), self or external
python run.py --way planned --backend harness.scripted:AlwaysInvalidPlanner --set dev   # your reject exit; free
python run.py --way planned --backend harness.scripted:OffPlanExecutor --set dev       # your boundary; free
python run.py --way planned --critique external --backend harness.scripted:DraftNamesUnseenFile --set dev  # free
python run.py --way notes --notes on --backend harness.scripted:ScriptedTriage --set dev  # Part G's plumbing; free

python run.py --way agent --set eval --runs 3                       # Part F: Assignment 1's agent, 18 runs
python run.py --way planned --critique off --set eval --runs 3      # Part F: 18 runs
python run.py --way planned --critique self --set eval --runs 3     # Part F: 18 runs
python run.py --way planned --critique external --set eval --runs 3 # Part F: 18 runs
python run.py --way notes --notes off --issues 4203,4204,4206 --runs 2   # Part G: 6 runs
python run.py --way notes --notes on --issues 4203,4204,4206 --runs 2    # Part G: 6 runs

make ping                                                # check your model: two tiny calls
make bounds-smoke                                        # the agent against a model that never stops; free
make reset                                               # archive old comments before a measurement
make check-02                                            # the Assignment 2 checker
```

Each run writes `runs/<run_id>.jsonl` and appends a line to
`runs/_ledger.jsonl`. The runner stamps a fresh `run_id` on every run, and the
tracker stamps it on every comment that run posts, so each run is checked on its
own comments and nothing else. Every run records `lab: "02"`, its `--critique` and
its `--notes` in its first line, and `make check-02` reads only this assignment's
runs. A `--way notes` run also writes its progress file, `runs/<run_id>.progress.json`. The scripted models cost nothing and are left out of the
checker's results. On a free tier, or if you hit rate limits, add `--jobs 1`: the
harness waits as long as your vendor asks before it retries, with either backend. `python run.py
--help` lists every option.

## On a free tier: splitting the work over days

A free tier limits requests a day as well as a minute: Gemini's free tier allows 500
a day per model. Assignment 2's runs make about this many model calls each,
measured on the course's scripted model with real prompts, issues and results:

| Configuration | Model calls a run | Parts F and G |
|---|---|---|
| `--way agent` | 4 to 12: its loop's step bound is 12 | 18 runs: 72 to 216 calls |
| `--way planned --critique off` | 4 to 8 | 18 runs: up to 144 |
| `--way planned --critique self` | up to 11 | 18 runs: up to 198 |
| `--way planned --critique external` | up to 9 | 18 runs: up to 162 |
| `--way notes` | 10 to 16 | 12 runs: 120 to 192 |

Parts F and G make about 500 to 900 calls (about 625 measured on Claude Haiku 5.5),
and development 100 or more, so on a free tier plan two or three days. Three things
make that easy:

- **Running the same command again resumes it.** On the evaluation issues, the
  measured runs and Part G's included, it skips the runs that configuration (way,
  `--critique`, `--notes`, model) has already finished. Run
  `python run.py --way planned --critique self --set eval --runs 3` on Monday and
  again on Tuesday, and Tuesday's run does only what Monday's left. Runs on the
  development issues (`--set dev`) always run anew.
- **The daily limit stops the sweep cleanly.** When your vendor refuses a call
  because the day's quota is spent, the run it interrupted ends `quota`, which
  never counts as finished, and the sweep stops with "daily limit reached; run the
  same command again when it resets; finished runs are kept". A per-minute limit,
  or an overloaded model, is waited out as long as the vendor asks; a call still
  refused after six retries ends its run `rate_limited`, which never counts as
  finished either, and running the command again redoes it.
- **Discard starts a configuration over.** Every configuration's runs must come
  from one version of your code. If you change the code after some runs,
  `python run.py --discard --way planned --critique self --set eval` moves that
  configuration's evaluation runs, and their comments, to `runs/discarded/`, where
  the checker does not read them; their tokens stay in the ledger. Then run it
  again.

Scripted models (`--backend harness.scripted:...`) cost no requests at all. They
answer by fixed rules (`checks/FORMATS.md`, section 10.9): `ScriptedTriage`, for
one, searches for `dedupeKey`, reads `src/ingest/dedupe.ts`, drafts its comment,
accepts in a self critique, and, offered no tool, answers with the draft comment
when the request mentions "rewrite", "draft" or "comment", and "yes" otherwise.

## The rules the harness enforces

- **Success is read from the tracker, never from the agent.** Assignment 1's
  `eval/check_triage.py` decides; the model's closing words decide nothing.
- **Every run has a hard ceiling** (`session_token_ceiling`), and **every
  assignment has one** (`lab_token_ceiling`). The runner stops starting runs at the
  second. Ask before you pass `--over-budget`.
- **The plan is logged before anything runs.** `trace.plan` refuses anything that
  is not a plan, and `trace.event` refuses an `off_plan`, `revision`, `critique`,
  `compaction` or `question` line without its fields.
- **Every number carries its run count and its spread.**
- **Prompts live in `prompts/`**, and a layer held only by a prompt is empty.
- **Disclose AI assistance** in each report: which tool, what it wrote, what you
  checked.

## Submitting an assignment

Your copy of this repository is private. When you create it, add the course
staff's GitHub account as a collaborator (**Settings**, then **Collaborators**)
and post its URL on the assignment in Canvas: that is how staff find and read
your work.

Run `make check-02` first; it is the same checker staff run. Commit everything,
including `runs/` and `tracker/` (the checker reads both), then tag the commit
and push both the commit and the tag. A tag you have not pushed has not been
submitted.

```bash
make check-02
git add -A
git commit -m "Assignment 2"
git tag lab-02
git push
git push origin lab-02
```
