"""Blackie Housekeeping Scanner — session delta detection engine."""

import json, os, sqlite3, sys, time

TRACKER_PATH = os.path.join(os.path.dirname(__file__), "tracker.json")
STATE_DB = os.path.expanduser("~/.hermes/state.db")

def load_tracker():
    try:
        with open(TRACKER_PATH) as f: return json.load(f)
    except: return {}

def get_user_msg_count(session_id):
    """Count only user messages — idle detection must ignore assistant/tool msgs."""
    try:
        conn = sqlite3.connect(STATE_DB)
        row = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=? AND role='user'",
            (session_id,)
        ).fetchone()
        conn.close()
        return row[0] if row else 0
    except:
        return 0

def get_active_sessions(limit=10):
    sessions = []
    try:
        conn = sqlite3.connect(STATE_DB)
        for row in conn.execute(
            "SELECT id, source, started_at, ended_at, message_count FROM sessions "
            "WHERE (ended_at IS NOT NULL) "
            "   OR (ended_at IS NULL AND source NOT IN ('cron','gateway') AND message_count > 0) "
            "ORDER BY CASE WHEN ended_at IS NULL THEN 0 ELSE 1 END, "
            "         COALESCE(ended_at, started_at) DESC "
            "LIMIT ?", (limit,)
        ):
            sessions.append({"id": row[0], "source": row[1] or "", "started_at": row[2], "ended_at": row[3], "message_count": row[4] or 0})
        conn.close()
    except Exception as e: print(f"Scanner: {e}", file=sys.stderr)
    return sessions

def scan(limit=10):
    tracker = load_tracker()
    tracker_sessions = tracker.get("sessions", {})
    sessions = get_active_sessions(limit)
    result = {"scanned_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "active_sessions": len(sessions), "sessions": [], "has_new": False}
    for s in sessions:
        sid = s["id"]
        t = tracker_sessions.get(sid, {})
        is_active = s["ended_at"] is None
        last_count = t.get("last_msg_count", 0)
        current_count = get_user_msg_count(sid)  # Only Nija's messages
        idle = (current_count == last_count)
        has_new = is_active or not t.get("last_msg_id")
        result["sessions"].append({
            "id": sid, "source": s["source"],
            "ended_at": str(s["ended_at"]) if s["ended_at"] else None,
            "msg_count": current_count,
            "last_msg_count": last_count,
            "idle": idle,
            "is_active": is_active,
            "has_new": has_new
        })
        if has_new:
            result["has_new"] = True
        # Persist updated state for next comparison
        tracker_sessions[sid] = {
            "last_msg_count": current_count,
            "last_checked": time.strftime("%Y-%m-%dT%H:%M:%S")
        }
    tracker["sessions"] = tracker_sessions
    with open(TRACKER_PATH, "w") as f:
        json.dump(tracker, f, indent=2)
    return result

if __name__ == "__main__":
    limit = 10
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--limit" and i+1 < len(args): limit = int(args[i+1])
    r = scan(limit)
    print(json.dumps(r, indent=2, ensure_ascii=False))
