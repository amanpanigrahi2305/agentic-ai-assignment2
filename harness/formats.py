"""The formats a checker reads. checks/FORMATS.md documents each one in prose."""

from __future__ import annotations

import re

LABELS = ("bug", "feature", "question", "docs")

# Why a run ended. Written by the harness loop, never reported by the model.
TERMINAL_REASONS = (
    "model_stopped",  # the model ended its turn without asking for a tool
    "turn_limit",     # the loop reached its maximum number of steps
    "token_budget",   # the loop's own token budget was reached
    "wall_clock",     # the loop ran out of time
    "tool_error",     # a tool failed in a way the loop could not continue from
    "refusal",        # the model declined (stop_reason "refusal")
    "completed",      # written by the runner for ways that have no loop
    "crashed",        # written by the runner when your way raised; see run_end.error
    "escalated",      # the way handed the issue to a person: no valid plan, or a step it could not run
    "quota",          # written by the runner: the vendor's daily quota stopped the run; never counted as finished
    "rate_limited",   # written by the runner: the vendor still refused after every retry; never counted as finished
)

# A run that ended with one of these is not finished: running the same command again redoes it.
UNFINISHED = ("quota", "rate_limited")

# Assignment 2. What a model call was for: trace.model_call(step, response, purpose=...).
# None for a call that is none of these (Assignment 1's ways, a compaction's summary,
# Part G's questions).
PURPOSES = ("plan", "revise", "execute", "critique")

# Assignment 2, Part D: the second pass's modes (run.py --critique), and Part G's
# progress file (run.py --notes).
CRITIQUE_MODES = ("off", "self", "external")
NOTES_MODES = ("off", "on")

# The status of a plan step. You may add values of your own.
PLAN_STATUSES = ("pending", "done", "failed")

# In a plan, an argument the executor fills in at run time, from earlier results.
FILL = "$fill"

# The trace lines Assignment 2 names, written with trace.event(kind, **fields), and
# the fields each must carry. Other kinds of event are yours to add.
EVENT_FIELDS = {
    "off_plan": ("step", "tool"),                    # a call the executor refused
    "revision": ("checkpoint", "version", "valid"),  # an attempt to revise the plan
    "critique": ("round", "mode", "result", "reason", "changed", "draft"),  # one round of the second pass
    "compaction": ("threshold", "tokens"),           # older turns replaced by a summary
    "question": ("path", "answer"),                  # Part G: "Has this run seen <path>?" and the answer
    "schema": ("errors",),                           # a plan that broke agent/plan_schema.json, and how
}

# Line types the harness writes itself; trace.event cannot use them.
RESERVED_TYPES = ("run_start", "model_call", "tool_call", "end", "run_end", "plan")

_LABEL_LINE = re.compile(r"^\s*label\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_FILE_LINE = re.compile(r"^\s*file\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)

# Every issue body ends with one of these (checks/FORMATS.md, section 10.8).
SENTINEL = re.compile(r"<!--\s*sentinel:\s*(SNTL-[A-Z]+(?:-[A-Z]+)+)\s*-->")


_HIT = re.compile(r"^([\w./-]+\.\w+):\d+: ", re.MULTILINE)


def result_paths(name: str, tool_input: dict, content: str, is_error: bool) -> list[str]:
    """The files a tool call returned, as its tool_call line records them (`paths`):
    every path in a search_repo result, the file a read_file call read, and nothing
    from any other tool or from an error."""
    if is_error:
        return []
    if name == "search_repo":
        return list(dict.fromkeys(_HIT.findall(content or "")))
    if name == "read_file":
        path = normalize_path(str((tool_input or {}).get("path", "")))
        return [path] if path and path != "none" else []
    return []


def normalize_path(path: str | None) -> str | None:
    """Canonical form of a file answer: relative to fixtures/repo, forward slashes, or 'none'."""
    if path is None:
        return None
    p = path.strip().strip("`'\"").strip()
    p = p.replace("\\", "/")
    for prefix in ("./", "fixtures/repo/", "repo/"):
        if p.startswith(prefix):
            p = p[len(prefix):]
    p = p.rstrip(".,;")
    if p.lower() in ("none", "n/a", "-", ""):
        return "none"
    return p


def parse_triage_comment(body: str) -> tuple[str | None, str | None]:
    """Read the first 'label:' and 'file:' lines of a triage comment.

    Keys are case-insensitive. Backticks and a leading './' around the path are
    ignored. A missing line comes back as None.
    """
    label_match = _LABEL_LINE.search(body or "")
    file_match = _FILE_LINE.search(body or "")
    label = label_match.group(1).strip().strip("`'\"").lower() if label_match else None
    file = normalize_path(file_match.group(1)) if file_match else None
    return label, file


def format_triage_comment(label: str, file: str | None, note: str = "") -> str:
    """The comment body the assignment expects: two lines, then anything you like."""
    body = f"label: {label}\nfile: {normalize_path(file) or 'none'}"
    return f"{body}\n\n{note.strip()}" if note.strip() else body
