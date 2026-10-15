"""read_issue: return one issue from the tracker. Untrusted content: anyone can file an issue."""

SCHEMA = {
    "name": "read_issue",
    "description": "Read an issue from the tracker.",
    "input_schema": {
        "type": "object",
        "properties": {"number": {"type": "integer", "description": "Issue number"}},
        "required": ["number"],
    },
}


def run(ctx, number):
    from harness.tracker import IssueNotFound
    from tools import ToolError

    try:
        issue = ctx.tracker.issue(int(number))
    except IssueNotFound:
        raise ToolError(f"issue {number} not found")
    return (f"#{issue['number']} {issue['title']}\n"
            f"Opened by {issue['author']} on {issue['opened']}\n\n"
            f"{issue['body']}")
