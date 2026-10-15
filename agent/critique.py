"""Assignment 2, Part D: the second pass before posting. This file is yours.

Two ways to read a drafted comment before it is posted (Lecture 2, slides 31 to 34).
The checker runs your planned way in each mode against scripted models, so keep
these exact signatures (checks/FORMATS.md, section 10.2). You may add keyword
arguments with defaults; the checker passes only these.

    verify(draft, ctx) -> {"passed": bool, "reasons": [str, ...]}

        The external mode: checks in code, against the repository and this run's
        own record. Four checks:
          1. the draft parses: a `label:` line with a known label, and a `file:`
             line with a path or none (section 1; harness.formats.parse_triage_comment);
          2. a path it names exists in the repository (ctx.root / "fixtures" / "repo");
          3. this run saw that path: a search_repo result or a read_file call in this
             run's trace returned it. Each tool_call line's `paths` field lists the
             files it returned; read the trace so far with
             harness.trace.read_trace(ctx.trace.path);
          4. the label and the file agree: a question names none, and every other
             label names a file.
        "reasons" says why each failed check failed; it is empty when all pass.
        verify reads only what the run itself can see: never the answer key, and
        never Assignment 1's grounded check in eval/. The checker flags a second
        pass that does.

    self_critique(client, draft, evidence, trace=None) -> {"decision": "accept" | "revise", "reason": str | None}

        The self mode: one model call that rereads the draft, given the issue and
        what the run's steps returned (`evidence`, a dict of your design), and
        accepts it or asks for a revision with a reason. Given a trace, trace the
        call: trace.model_call(n, response, purpose="critique").

    draft   the comment your executor drafted, the text post_comment would post
    ctx     the run's harness.runner.WayContext
    client  harness.client.ModelClient

The loop that uses them, its rewrite call and MAX_ROUNDS live in ways/planned.py.
Keep your prompts in prompts/.
"""

from __future__ import annotations


def verify(draft: str, ctx) -> dict:
    raise NotImplementedError("Assignment 2 Part D: the external checks")


def self_critique(client, draft: str, evidence: dict, trace=None) -> dict:
    raise NotImplementedError("Assignment 2 Part D: the self critique")
