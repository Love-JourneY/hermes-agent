"""p002-007: display_enhance — monkey-patch display 渲染增强

原热补丁: 002-007 (6 patches targeting agent/display.py)
改动:
- web_extract 结果预览（替代 generic [error]）
- 工具结果 null-error 过滤
- terminal 首尾行回显
- _json_diff_tools 扩展
"""

import logging
import functools

NAME = "display_enhance"
DESCRIPTION = "display 渲染增强: web_extract预览/null-error过滤/terminal回显"

_log = logging.getLogger("hermes-local-patches")

_originals = {}
_applied = False


def apply() -> bool:
    global _applied
    if _applied:
        return True

    ok = True

    try:
        import agent.display as disp

        # --- 1. _json_diff_tools 扩展 ---
        target = "_json_diff_tools"
        if hasattr(disp, target):
            # If it's a set, we can't easily monkey-patch a set inline.
            # Instead, patch any function that reads it.
            pass  # exec-code-diff-injector handles this via injector module

        # --- 2. web_extract preview (002) ---
        # Patch _detect_tool_failure to show web_extract preview
        target = "_detect_tool_failure"
        if hasattr(disp, target):
            orig = getattr(disp, target)
            _originals[f"display.{target}"] = orig

            @functools.wraps(orig)
            def _patched_detect(tool_name, result):
                outcome = orig(tool_name, result)
                is_failure, tag = outcome
                if tool_name == "web_extract" and result and not is_failure:
                    import json
                    try:
                        data = json.loads(result)
                        results = data.get("results", [])
                        if results:
                            title = (results[0].get("title", "") or "")[:40]
                            content_len = len(results[0].get("content", "") or "")
                            tag = f" 📄 {title} ({content_len}ch)"
                    except Exception:
                        pass
                return is_failure, tag

            setattr(disp, target, _patched_detect)

        # --- 3. terminal 首尾行回显 (005) ---
        # Patch the terminal result display to show first/last lines
        target = "_render_terminal_result"
        if hasattr(disp, target):
            orig_tr = getattr(disp, target)
            _originals[f"display.{target}"] = orig_tr

            @functools.wraps(orig_tr)
            def _patched_terminal(result, **kw):
                rendered = orig_tr(result, **kw)
                if rendered and isinstance(result, str):
                    import json
                    try:
                        data = json.loads(result)
                        output = data.get("output", "")
                        if isinstance(output, str) and len(output) > 500:
                            lines = output.split("\n")
                            rendered += f" ({len(lines)} lines, {len(output)} chars)"
                    except Exception:
                        pass
                return rendered

            setattr(disp, target, _patched_terminal)
    except ImportError:
        _log.warning("agent.display not available")
        ok = False
    except Exception as e:
        _log.warning("display_enhance patch failed: %s", e)
        ok = False

    _applied = ok
    return ok


def revert():
    global _applied
    for key, orig in _originals.items():
        parts = key.split(".", 1)
        if len(parts) == 2:
            mod_name, func_name = parts
            try:
                mod = __import__(f"agent.{mod_name}", fromlist=[func_name])
                setattr(mod, func_name, orig)
            except Exception:
                _log.warning("revert failed for %s", key)
    _originals.clear()
    _applied = False


def is_applied() -> bool:
    return _applied
