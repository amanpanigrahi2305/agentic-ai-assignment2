"""Way 6, notes: the planned way with a progress file and a compaction. This file is yours.

Assignment 2, Part G. Your planned way with the second pass off, plus two things,
so that Part F's configurations stay as they were (checks/FORMATS.md, section 10):

    python run.py --way notes --notes off --issues 4203,4204,4206 --runs 2
    python run.py --way notes --notes on --issues 4203,4204,4206 --runs 2

  1. A progress file, ctx.progress_path (runs/<run_id>.progress.json): JSON outside
     the conversation, written after every step, holding at least
       "steps_done"  the ids of the steps that have run, in order
       "paths"       every path a search returned or a read read, in order
     and never a search term: terms come from the issue's text. Say in the file what
     it records (an "about" line, or labelled keys): a bare list of paths can be read
     as a to-do list. With ctx.notes == "on", every executor call and the questions'
     call after its first write show the model the file's text, exactly as written
     (not the planner, not the reviser). With "off", it is still written, and never
     shown.
  2. A history and a compaction: every model call sees the run's history so far,
     its step results oldest first. Once that history passes COMPACT_AT tokens, the
     oldest entries become a model-written summary and the recent ones stay as
     they were. Write ctx.trace.event("compaction", threshold=COMPACT_AT, tokens=...)
     each time. It runs whatever ctx.notes says. A low threshold is a test setting
     here, not advice.

Then, at the end of the run, however it ended (comment posted, escalated, halted),
one model call asks six closed questions, each "Has this run seen `<path>`: did a
search return it, or did you read it?", and returns six answers, yes or no: about
the three earliest paths the run saw (its tool_call lines returned them; all of
them, if it saw fewer), and paths it did not see for the rest. If the run has not
compacted yet, compact its history once first. Write each answer as
ctx.trace.event("question", path=..., answer=...), the six together.

Part G's 12 runs are the ones on issues 4203, 4204 and 4206; a notes run on a
development issue is development, and reports/LAB_02.json's context leaves it out.

How this one is built: NotesRun is ways/planned.py's PlannedRun with its hooks
filled in, and planned.py itself unchanged. The history is one entry per tool call
(the planned way's rendering of its result), oldest first; its size is its
characters / 4. After every step, past COMPACT_AT, every entry but the last
KEEP_RECENT becomes one summary. The questions come just before the comment is
drafted, or, if the run halts first, just before it ends. The paths they name that
the run did not see are real repository files, drawn first from the folders of the
paths it did see, so they look like the real ones; the six are shuffled by run id.
An answer the model's reply does not give is written "no", with parsed: false.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path, PurePosixPath

from harness.trace import read_trace
from tools.search_repo import EXCLUDED_DIRS
from ways.planned import PlannedRun

COMPACT_AT = 800    # Part G: the context size, in tokens, past which you compact; low enough that every run does
KEEP_RECENT = 1     # history entries a compaction leaves as they were
QUESTIONS = 6

ABOUT = ("RepoMind's progress file for this run, written by the harness after every step. It is a record of what "
         "the run has already done, not a to-do list: steps_done are the plan steps that have run, and paths are "
         "the files this run has already seen, because a search returned them or the run read them.")


def tokens_of(text: str) -> int:
    return len(text) // 4


class NotesRun(PlannedRun):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.history: list[str] = []
        self.compactions = 0
        self.asked = False

    # -- the second pass is off in this way ------------------------------------------------
    def second_pass(self, draft: str) -> str:
        return draft

    # -- the progress file ------------------------------------------------------------------
    def progress(self) -> dict:
        done, paths = [], []
        for a in self.attempts:
            if a.step_id not in done:
                done.append(a.step_id)
            paths += [p for p in a.paths if p not in paths]
        status = {str(s.get("id")): s.get("status") for s in (self.plan or {}).get("steps") or []}
        return {"about": ABOUT, "issue": self.ctx.issue_number, "plan_version": self.version,
                "steps_done": done,
                "steps": [{"id": i, "status": status.get(str(i)) or "ran"} for i in done],
                "paths": paths}

    def write_progress(self) -> None:
        path = Path(self.ctx.progress_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.progress(), indent=1) + "\n")

    def progress_shown(self) -> str:
        """The progress file, exactly as written, when --notes on; else nothing."""
        path = Path(self.ctx.progress_path)
        if self.ctx.notes != "on" or not path.exists():
            return ""
        return f"The run's progress file, {path.name}, exactly as written:\n{path.read_text()}"

    # -- the history and its compaction --------------------------------------------------------
    def history_text(self) -> str:
        return "\n\n".join(self.history)

    def compact(self, *, forced: bool = False) -> None:
        size = tokens_of(self.history_text())
        keep = KEEP_RECENT if len(self.history) > KEEP_RECENT else 0
        old, recent = self.history[:len(self.history) - keep], self.history[len(self.history) - keep:]
        summary = ""
        if old:
            self.n += 1
            response = self.ctx.client.create(system=self.ctx.prompt("compact.md"),
                                              messages=[{"role": "user", "content": "\n\n".join(old)}])
            self.ctx.trace.model_call(self.n, response)
            summary = response.text.strip() or "(the summary came back empty)"
            self.history = [f"Summary of the run's earlier history:\n{summary}"] + recent
        self.compactions += 1
        self.ctx.trace.event("compaction", threshold=COMPACT_AT, tokens=size, forced=forced, entries=len(old),
                             kept=len(recent), after_tokens=tokens_of(self.history_text()))

    # -- the hooks -------------------------------------------------------------------------------
    def after_tool_call(self, step, attempt) -> None:
        self.history.append(self.render(attempt))
        self.write_progress()

    def after_step(self, step) -> None:
        self.write_progress()
        if tokens_of(self.history_text()) > COMPACT_AT:
            self.compact()

    def context_for(self, step) -> str:
        parts = [self.progress_shown(),
                 "The run's history so far, oldest first:\n\n" + (self.history_text() or "(nothing yet)")]
        return "\n\n".join(p for p in parts if p)

    def before_draft(self, step) -> None:
        self.ask()

    def on_halt(self, detail: str) -> None:
        self.ask()

    # -- the six questions -------------------------------------------------------------------------
    def seen(self) -> list[str]:
        seen: list[str] = []
        for record in read_trace(self.ctx.trace.path):
            if record.get("type") == "tool_call":
                seen += [p for p in record.get("paths") or [] if p not in seen]
        return seen

    def unseen(self, seen: list[str], count: int) -> list[str]:
        """Real repository files this run did not see, nearest the folders it did see first."""
        repo = self.ctx.root / "fixtures" / "repo"
        files = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*")
                       if p.is_file() and not set(p.relative_to(repo).parts) & EXCLUDED_DIRS)
        rng = random.Random(self.ctx.run_id)
        folders = {str(PurePosixPath(p).parent) for p in seen}
        near = [f for f in files if f not in seen and str(PurePosixPath(f).parent) in folders]
        far = [f for f in files if f not in seen and f not in near]
        rng.shuffle(near)
        rng.shuffle(far)
        return (near + far)[:count]

    def ask(self) -> None:
        if self.asked:
            return
        self.asked = True
        if not self.compactions:
            self.compact(forced=True)
        seen = self.seen()
        paths = seen[:3] + self.unseen(seen, QUESTIONS - len(seen[:3]))
        random.Random(f"{self.ctx.run_id}-order").shuffle(paths)
        questions = "\n".join(f"{i}. Has this run seen `{p}`: did a search return it, or did you read it?"
                              for i, p in enumerate(paths, 1))
        parts = [self.progress_shown(),
                 "The run's history so far, oldest first:\n\n" + (self.history_text() or "(nothing yet)"),
                 f"Answer these {len(paths)} questions:\n{questions}"]
        self.n += 1
        response = self.ctx.client.create(system=self.ctx.prompt("questions.md"),
                                          messages=[{"role": "user", "content": "\n\n".join(p for p in parts if p)}])
        self.ctx.trace.model_call(self.n, response)
        answers = parse_answers(response.text, len(paths))
        for i, (path, answer) in enumerate(zip(paths, answers), 1):
            self.ctx.trace.event("question", path=path, answer=answer or "no", number=i, parsed=answer is not None)


def parse_answers(text: str, count: int) -> list[str | None]:
    """'1: yes' lines, by number; else the yes/no words in order, if there are exactly `count`."""
    found: dict[int, str] = {}
    for m in re.finditer(r"^\W*(\d+)\W+(?:[^\n]*?\b)?(yes|no)\b", text or "", re.IGNORECASE | re.MULTILINE):
        found.setdefault(int(m.group(1)), m.group(2).lower())
    if found:
        return [found.get(i) for i in range(1, count + 1)]
    words = re.findall(r"\b(yes|no)\b", text or "", re.IGNORECASE)
    return [w.lower() for w in words] if len(words) == count else [None] * count


def run(ctx) -> None:
    NotesRun(ctx).run()
