"""Blackie Housekeeping Scanner — session delta detection engine."""

import json, os, sqlite3, sys, time

TRACKER_PATH = os.path.join(os.path.dirname(__file__), "tracker.json")
STATE_DB = os.path.expanduser("~/.hermes/state.db")

def load_tracker():
    try:
        with open(TRACKER_PATH) as f: return json.load(f)
    except: return {}

def get_active_sessions(limit=10):
    sessions = []
    try:
        conn = sqlite3.connect(STATE_DB)
        for row in conn.execute(
            "SELECT id, source, started_at, ended_at, message_count "
            "FROM sessions WHERE ended_at IS NOT NULL "
            "ORDER BY ended_at DESC LIMIT ?", (limit,)
        ):
            sessions.append({"id": row[0], "source": row[1] or "", "started_at": row[2], "ended_at": row[3], "message_count": row[4] or 0})
        conn.close()
    except Exception as e: print(f"Scanner: {e}", file=sys.stderr)
    return sessions

def scan(limit=10):
    tracker = load_tracker()
    sessions = get_active_sessions(limit)
    result = {"scanned_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "active_sessions": len(sessions), "sessions": [], "has_new": False}
    for s in sessions:
        sid = s["id"]
        t = tracker.get(sid, {})
        result["sessions"].append({"id": sid, "source": s["source"], "ended_at": str(s["ended_at"]), "msg_count": s["message_count"], "last_checked_msg_id": t.get("last_msg_id"), "has_new": True})
        if not t.get("last_msg_id"): result["has_new"] = True
    return result

if __name__ == "__main__":
    limit = 10
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--limit" and i+1 < len(args): limit = int(args[i+1])
    r = scan(limit)
    print(json.dumps(r, indent=2, ensure_ascii=False))
