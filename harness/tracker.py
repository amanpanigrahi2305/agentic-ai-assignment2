"""The mock issue tracker.

Issues are Markdown files in fixtures/issues/ (evaluation) and
fixtures/issues/dev/ (development), each with a small front-matter header.
Comments are appended to tracker/comments.jsonl, and **every comment is stamped
with the run_id of the run that wrote it**, by the harness, not the model.

That stamp is what makes a run attributable: a check
reads the comments for *its* run_id, so an earlier run's comment can never
pass a later run. The model never sees comments at all: read_issue returns the
issue alone, so no run can copy another run's answer.

    python -m harness.tracker reset    # archive comments.jsonl and start empty
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import yaml

from harness import ROOT

_lock = threading.Lock()


class IssueNotFound(KeyError):
    pass


class Tracker:
    def __init__(self, root: Path | None = None, state_dir: Path | None = None):
        self.root = Path(root or ROOT)
        self.issue_dir = self.root / "fixtures" / "issues"
        self.state_dir = Path(state_dir or self.root / "tracker")
        self.comments_path = self.state_dir / "comments.jsonl"

    # -- issues -------------------------------------------------------------------
    def _issue_path(self, number: int) -> Path:
        for candidate in (self.issue_dir / f"{number}.md", self.issue_dir / "dev" / f"{number}.md"):
            if candidate.exists():
                return candidate
        raise IssueNotFound(number)

    def issue(self, number: int) -> dict:
        text = self._issue_path(int(number)).read_text()
        _, header, body = text.split("---", 2)
        meta = yaml.safe_load(header)
        return {**meta, "body": body.strip()}

    def issue_numbers(self, which: str = "eval") -> list[int]:
        folder = self.issue_dir / "dev" if which == "dev" else self.issue_dir
        return sorted(int(p.stem) for p in folder.glob("*.md"))

    # -- comments -----------------------------------------------------------------
    def post_comment(self, run_id: str, number: int, body: str) -> dict:
        self._issue_path(int(number))  # refuse comments on issues that do not exist
        with _lock:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            seq = 1
            if self.comments_path.exists():
                with self.comments_path.open() as existing:
                    seq += sum(1 for _ in existing)
            comment = {"id": seq, "run_id": run_id, "issue": int(number), "body": body,
                       "posted_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            with self.comments_path.open("a") as fh:
                fh.write(json.dumps(comment) + "\n")
        return comment

    def comments(self, run_id: str | None = None, issue: int | None = None) -> list[dict]:
        if not self.comments_path.exists():
            return []
        rows = [json.loads(line) for line in self.comments_path.read_text().splitlines() if line.strip()]
        return [c for c in rows
                if (run_id is None or c["run_id"] == run_id)
                and (issue is None or c["issue"] == int(issue))]

    def reset(self) -> Path | None:
        """Archive the current comments and start empty. Returns the archive path."""
        if not self.comments_path.exists():
            return None
        archive = self.state_dir / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / f"comments-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        self.comments_path.rename(target)
        return target


if __name__ == "__main__":
    if sys.argv[1:] == ["reset"]:
        moved = Tracker().reset()
        print(f"tracker reset; old comments archived to {moved}" if moved else "tracker already empty")
    else:
        print(__doc__)
