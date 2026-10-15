"""post_comment: write a comment on an issue. The only write RepoMind has in Assignment 1,
and it is public: whoever filed the issue can read it."""

SCHEMA = {
    "name": "post_comment",
    "description": "Post a comment on an issue.",
    "input_schema": {
        "type": "object",
        "properties": {
            "number": {"type": "integer", "description": "Issue number"},
            "body": {"type": "string", "description": "Comment text"},
        },
        "required": ["number", "body"],
    },
}


def run(ctx, number, body):
    from harness.tracker import IssueNotFound
    from tools import ToolError

    if not str(body).strip():
        raise ToolError("comment body is empty")
    try:
        comment = ctx.tracker.post_comment(ctx.run_id, int(number), str(body))
    except IssueNotFound:
        raise ToolError(f"issue {number} not found")
    return f"Posted comment {comment['id']} on issue {number}."
