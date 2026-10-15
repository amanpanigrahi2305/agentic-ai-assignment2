"""read_file: return one file of the private codebase, whole.

New in Assignment 2, and as plain as the other three: Assignment 3 rewrites all
four. It reads the same files search_repo searches: everything under
fixtures/repo except config/. A path is relative to fixtures/repo, as search
results print it.
"""

from pathlib import Path

SCHEMA = {
    "name": "read_file",
    "description": "Read a file.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "File path"}},
        "required": ["path"],
    },
}

MAX_CHARS = 20_000   # a longer file comes back cut, with a note saying so


def run(ctx, path):
    from harness.formats import normalize_path
    from tools import ToolError
    from tools.search_repo import EXCLUDED_DIRS

    rel = normalize_path(str(path))
    if rel in (None, "none"):
        raise ToolError("path is empty")
    root = Path(ctx.repo_root).resolve()
    target = (root / rel).resolve()
    if root != target and root not in target.parents:
        raise ToolError(f"{path} is outside the repository")
    parts = target.relative_to(root).parts
    if set(parts) & EXCLUDED_DIRS:
        raise ToolError(f"{path} is not readable")
    if not target.is_file():
        raise ToolError(f"no such file: {path}")
    try:
        text = target.read_text()
    except UnicodeDecodeError:
        raise ToolError(f"{path} is not a text file")
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n[cut at {MAX_CHARS:,} of {len(text):,} characters]"
    return text
