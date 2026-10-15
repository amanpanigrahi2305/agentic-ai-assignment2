"""search_repo: literal, case-insensitive text search over the private codebase.

Searches every text file under fixtures/repo except config/. Results come back
in path order, one line each, as path:line: excerpt.
"""

from pathlib import Path

SCHEMA = {
    "name": "search_repo",
    "description": "Search the code.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text to look for"},
            "max_results": {"type": "integer", "description": "How many results"},
        },
        "required": ["query"],
    },
}

EXCLUDED_DIRS = {"config", "node_modules", ".git"}
HARD_CAP = 20


def _files(root: Path):
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not (set(rel.parts) & EXCLUDED_DIRS):
            yield path, rel.as_posix()


def run(ctx, query, max_results=10):
    from tools import ToolError

    needle = str(query).strip().lower()
    if not needle:
        raise ToolError("query is empty")
    limit = max(1, min(int(max_results), HARD_CAP))
    hits = []
    for path, rel in _files(Path(ctx.repo_root)):
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            if needle in line.lower():
                hits.append(f"{rel}:{number}: {line.strip()[:160]}")
                if len(hits) >= limit:
                    return "\n".join(hits)
    return "\n".join(hits) if hits else "No matches."
