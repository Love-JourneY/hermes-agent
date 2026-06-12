"""Blackie Housekeeping Plugin v1.0.0

Session delta scanner for semantic maintenance intelligence.
Tracks per-session last_checked_message_id via tracker.json.
Named after the cron job — serves ALL maintenance dimensions.
"""

import os
import json
import time
from typing import Optional, Dict, Any

TRACKER_PATH = os.path.join(os.path.dirname(__file__), "tracker.json")


def load_tracker() -> dict:
    try:
        with open(TRACKER_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_tracker(data: dict) -> None:
    with open(TRACKER_PATH, "w") as f:
        json.dump(data, f, indent=2)


def get_last_checked(session_id: str) -> Optional[int]:
    data = load_tracker()
    entry = data.get(session_id, {})
    return entry.get("last_msg_id")


def set_last_checked(session_id: str, msg_id: int) -> None:
    data = load_tracker()
    data[session_id] = {
        "last_msg_id": msg_id,
        "last_checked": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    save_tracker(data)


def on_post_tool_call(tool_name="", args=None, result=None, **kwargs):
    return None


def register(ctx):
    ctx.register_hook("post_tool_call", on_post_tool_call)
