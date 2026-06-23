"""p008-012: tool_diffs — monkey-patch 工具 diff 输出

原热补丁: 008-tools-memory-diff / 009-tools-todo-diff / 011-tools-cron-diff / 012-tools-skill-manage-diff
目标: memory_tool / todo_tool / cronjob_tools / skill_manager_tool
改动: 工具结果加 diff 字段
"""

import logging
import functools

NAME = "tool_diffs"
DESCRIPTION = "memory/todo/cron/skill 工具 diff 输出"

_log = logging.getLogger("hermes-local-patches")

_originals = {}
_applied = False


def _wrap_tool(mod_name, func_names):
    """Wrapper factory for tool functions that add diff to result."""
    imported = []

    for fname in func_names:
        try:
            mod = __import__(mod_name, fromlist=[fname])
            if not hasattr(mod, fname):
                _log.warning("target not found: %s.%s", mod_name, fname)
                continue
            orig = getattr(mod, fname)

            @functools.wraps(orig)
            def wrapped(*args, _orig=orig, _fname=fname, **kwargs):
                result = _orig(*args, **kwargs)
                # Add diff field from inner tool calls if present
                if isinstance(result, dict):
                    # Check for diff in result
                    if "diff" not in result:
                        # Look for diff in nested data
                        data = result.get("data") or result.get("result") or {}
                        if isinstance(data, dict) and data.get("diff"):
                            result["diff"] = data["diff"]
                return result

            setattr(mod, fname, wrapped)
            _originals[f"{mod_name}.{fname}"] = orig
            imported.append(fname)
        except ImportError:
            _log.warning("module not available: %s", mod_name)

    return len(imported) > 0


def apply() -> bool:
    global _applied
    if _applied:
        return True

    ok = True

    # memory_tool: memory_tool (main entry)
    ok &= _wrap_tool("tools.memory_tool", ["memory_tool"])

    # todo_tool: todo_tool (main entry)
    ok &= _wrap_tool("tools.todo_tool", ["todo_tool"])

    # cronjob_tools: cronjob (tool entry)
    ok &= _wrap_tool("tools.cronjob_tools", ["cronjob"])

    # skill_manager_tool: skill_manage (tool entry)
    ok &= _wrap_tool("tools.skill_manager_tool", ["skill_manage"])

    _applied = ok
    return ok


def revert():
    global _applied
    for key, orig in _originals.items():
        parts = key.rsplit(".", 1)
        if len(parts) == 2:
            mod_name, func_name = parts
            try:
                mod = __import__(mod_name, fromlist=[func_name])
                setattr(mod, func_name, orig)
            except Exception:
                _log.warning("revert failed for %s", key)
    _originals.clear()
    _applied = False


def is_applied() -> bool:
    return _applied
