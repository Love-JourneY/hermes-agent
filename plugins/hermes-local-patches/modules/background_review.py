"""p013: background_review — monkey-patch read_file 权限"""
import logging
NAME = "background_review"
DESCRIPTION = "background_review read_file permission"
_log = logging.getLogger("hermes-local-patches")
_originals = {}
_applied = False

def apply() -> bool:
    global _applied
    if _applied:
        return True
    ok = True
    try:
        import agent.background_review as br
        import functools
        t = "_run_review_in_thread"
        if hasattr(br, t):
            orig = getattr(br, t)
            @functools.wraps(orig)
            def wrapped(*a, **kw):
                if "toolsets" in kw:
                    ts = list(kw["toolsets"])
                    if "file" not in ts:
                        ts.append("file")
                    kw["toolsets"] = ts
                return orig(*a, **kw)
            setattr(br, t, wrapped)
            _originals["br." + t] = orig
        else:
            _log.warning("target not found: %s", t)
            ok = False
    except Exception as e:
        _log.warning("background_review failed: %s", e)
        ok = False
    _applied = ok
    return ok

def revert():
    global _applied
    for k, o in _originals.items():
        try:
            import agent.background_review as br
            fn = k.split(".", 1)[1]
            setattr(br, fn, o)
        except Exception:
            pass
    _originals.clear()
    _applied = False

def is_applied() -> bool:
    return _applied
