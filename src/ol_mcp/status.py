"""MCP tool: get_translation_status for async translation progress polling."""
from __future__ import annotations

import json

from ol_mcp.task_tracker import TaskTracker


def get_translation_status(request_id: str, tracker: TaskTracker) -> str:
    """Poll the status of an async translation task.

    Returns a JSON string conforming to the standardized {success, content?, error?} shape.
    """
    task = tracker.get_task(request_id)
    if task is None:
        return json.dumps({
            "success": False,
            "error": {
                "code": "NOT_FOUND",
                "message": f"No task found with request_id '{request_id}'",
            },
        })

    content: dict = {
        "request_id": task.request_id,
        "status": task.status.value,
        "progress": task.progress,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }
    if task.status.value == "completed" and task.result:
        content["result"] = task.result
    if task.status.value == "failed" and task.error:
        content["error_details"] = task.error

    return json.dumps({"success": True, "content": content})
