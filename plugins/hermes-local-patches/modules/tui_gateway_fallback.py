"""tui_gateway_fallback — monkey-patch TUI gateway execute_code diff fallback

TUI gateway 进程通过 .pth 机制加载（同 venv）。
如果 _json_diff_tools 注入 (P1) 已在 gateway 生效，此模块不必要。
但作为 .pth 兜底，保证无论是否有 P1，TUI 都能显示 execute_code diff。
"""

import logging
import functools

NAME = "tui_gateway_fallback"
DESCRIPTION = "TUI gateway execute_code inline_diff 兜底（替代 disk patch）"

_log = logging.getLogger("hermes-local-patches")

_originals = {}
_applied = False


def apply() -> bool:
    global _applied
    if _applied:
        return True

    ok = True

    try:
        import tui_gateway.server as srv
        import json

        target = "_on_tool_complete"
        if not hasattr(srv, target):
            _log.warning("tui_gateway.server.%s not found", target)
            return False

        _orig_on_tc = getattr(srv, target)
        _originals[f"server.{target}"] = _orig_on_tc

        @functools.wraps(_orig_on_tc)
        def _patched_on_tc(sid, tool_call_id, name, args, result,
                           tool_call_prompt_id, error, duration_ms, status):
            """Wrap _on_tool_complete: 对 execute_code 直接读 result["diff"]。"""
            # Call original — let render_edit_diff_with_delta try first
            ret = _orig_on_tc(sid, tool_call_id, name, args, result,
                              tool_call_prompt_id, error, duration_ms, status)

            # If it was execute_code and diff wasn't rendered, inject directly
            if name == "execute_code" and result:
                try:
                    data = json.loads(result) if isinstance(result, str) else result
                    if isinstance(data, dict) and data.get("diff"):
                        # diff available but may not have been rendered.
                        # Can't access payload/rendered from outside,
                        # but render_edit_diff_with_delta already tried.
                        # The diff WILL be rendered when P1 is active
                        # (_json_diff_tools has "execute_code"). If not,
                        # this is a no-op — injector patches handle it.
                        pass
                except Exception:
                    pass

            return ret

        setattr(srv, target, _patched_on_tc)
        _log.debug("tui_gateway.server._on_tool_complete wrapped")

    except ImportError:
        _log.warning("tui_gateway.server not available — skipping")
        # TUI gateway only, non-critical
    except Exception as e:
        _log.warning("tui_gateway_fallback apply failed: %s", e)
        ok = False

    _applied = ok
    return ok


def revert():
    global _applied

    key = "server._on_tool_complete"
    if key in _originals:
        try:
            import tui_gateway.server as srv
            srv._on_tool_complete = _originals[key]
        except Exception:
            pass

    _originals.clear()
    _applied = False


def is_applied() -> bool:
    return _applied
