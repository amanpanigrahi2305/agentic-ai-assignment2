"""Run a way of doing the triage task.

    python run.py --way planned --set dev                         # one try on the dev issues
    python run.py --way planned --critique self --set dev         # with Part D's second pass
    python run.py --way agent --set eval --runs 3                 # Part F: Assignment 1's agent, 18 runs
    python run.py --way planned --critique external --set eval --runs 3   # Part F: one of three modes
    python run.py --way notes --notes on --issues 4203,4204,4206 --runs 2  # Part G: 6 runs
    python run.py --way planned --backend harness.scripted:AlwaysInvalidPlanner --set dev   # free
    python run.py --way agent --backend never-stops --set dev     # the agent's bounds, free

Each run writes runs/<run_id>.jsonl. Success is not decided here:
eval/check_triage.py reads the tracker for each run_id and decides.

Running the same command again skips the runs on the evaluation issues that this
configuration (way, --critique, --notes, backend) has already finished, so a
measurement can be split over days. Runs on the development issues always run anew.
If your vendor's daily quota runs out, the sweep stops; run the same command again
when it resets. To start a configuration over, on the same issues:

    python run.py --discard --way planned --critique self --set eval
"""

import argparse
import sys

from harness.runner import QUOTA_MESSAGE, discard, run_sweeps
from harness.tracker import Tracker


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--way", required=True, help="a module in ways/: direct, workflow, agent, hybrid, planned, notes")
    p.add_argument("--set", default="dev", choices=["dev", "eval"], help="which issues (default dev)")
    p.add_argument("--issues", help="comma-separated issue numbers; overrides --set")
    p.add_argument("--runs", type=int, default=1, help="sweeps over the issues (default 1)")
    p.add_argument("--start-sweep", type=int, default=1, help="number of the first sweep, to resume")
    p.add_argument("--backend", help="default: the provider in settings.yaml; never-stops, or a harness.scripted: model, tests your code for free")
    p.add_argument("--jobs", type=int, help="runs at once (default from settings.yaml)")
    p.add_argument("--critique", default="off", choices=["off", "self", "external"],
                   help="Part D's second pass before posting (default off); recorded in run_start")
    p.add_argument("--notes", default="off", choices=["off", "on"],
                   help="Part G: show the progress file to the model (default off); recorded in run_start")
    p.add_argument("--over-budget", action="store_true", help="ignore the assignment's token ceiling (ask first)")
    p.add_argument("--discard", action="store_true",
                   help="move this configuration's runs on these issues, and their comments, to runs/discarded/; "
                        "their tokens stay in the ledger")
    a = p.parse_args(argv)

    issues = ([int(x) for x in a.issues.split(",")] if a.issues
              else Tracker().issue_numbers(a.set))
    if a.discard:
        discard(a.way, issues, critique=a.critique, notes=a.notes)
        return 0
    sweeps = range(a.start_sweep, a.start_sweep + a.runs)
    rows = run_sweeps(a.way, issues, sweeps, a.backend, jobs=a.jobs, over_budget=a.over_budget,
                      critique=a.critique, notes=a.notes)
    tokens = sum(r["total_tokens"] for r in rows)
    cost = sum(r["cost_usd"] for r in rows)
    errors = sum(1 for r in rows if r["error"] and not (r["quota"] or r["rate_limited"]))
    print(f"\n{len(rows)} runs, {tokens:,} tokens, ${cost:.4f}, {errors} with errors")
    limited = sum(1 for r in rows if r["rate_limited"])
    if limited:
        print(f"{limited} runs stopped by rate limits are not finished: run the same command again to redo them"
              " (add --jobs 1 on a free tier)")
    if any(r["quota"] for r in rows):
        print(QUOTA_MESSAGE)
        return 0
    return 1 if errors == len(rows) and rows else 0


if __name__ == "__main__":
    sys.exit(main())
