"""RepoMind's tools, and the registry that runs them.

Assignment 2 has four: read_issue, search_repo, read_file (new) and post_comment.
Their definitions are plain on purpose. Assignment 3 rewrites all four against
Lecture 3's six rules, so do not polish them here.

A registry is bound to one run: post_comment stamps that run's ID on every
comment it writes. Build one per run with `default_tools(ctx)`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from tools import post_comment, read_file, read_issue, search_repo

_MODULES = (read_issue, search_repo, read_file, post_comment)


class ToolError(Exception):
    """A tool failed in a way the model can be told about. Becomes an is_error result."""


@dataclass
class ToolResult:
    content: str
    is_error: bool
    latency_s: float


@dataclass
class RunContext:
    run_id: str
    tracker: object      # harness.tracker.Tracker
    repo_root: object    # pathlib.Path to fixtures/repo


class ToolRegistry:
    def __init__(self, ctx: RunContext, modules=_MODULES):
        self.ctx = ctx
        self._tools = {m.SCHEMA["name"]: m for m in modules}

    @property
    def schemas(self) -> list[dict]:
        """Tool definitions in the order given, ready for ModelClient.create(tools=...)."""
        return [m.SCHEMA for m in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def call(self, name: str, tool_input: dict) -> ToolResult:
        """Run one tool. Expected failures come back as is_error results; anything
        else raises, and your loop decides what that means (terminal_reason tool_error)."""
        start = time.monotonic()
        module = self._tools.get(name)
        if module is None:
            return ToolResult(f"Error: no tool named {name!r}.", True, time.monotonic() - start)
        try:
            content = module.run(self.ctx, **(tool_input or {}))
            return ToolResult(content, False, time.monotonic() - start)
        except (ToolError, TypeError, ValueError) as exc:
            return ToolResult(f"Error: {exc}", True, time.monotonic() - start)


def default_tools(ctx: RunContext) -> ToolRegistry:
    return ToolRegistry(ctx)
