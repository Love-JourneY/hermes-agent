"""exec_code_diff — monkey-patch execute_code diff 渲染

P1: display._json_diff_tools 加 "execute_code"
P2: acp_adapter._format_execute_code_result 显示 diff
P3: wrap handle_function_call → 存 result 到 threading.local()
P4: wrap _rpc_server_loop → call_log.append 注入 result
P5: wrap _rpc_poll_loop  → call_log.append 注入 result
P6: wrap execute_code → 读 call_log → 提 diff 到 result["diff"]
"""

import logging
import functools
import json
import threading

NAME = "exec_code_diff"
DESCRIPTION = "execute_code 内部 diff 渲染到 TUI（替代 git-apply 方案）"

_log = logging.getLogger("hermes-local-patches")

_originals = {}
_applied = False

# 线程局部的 tool result 缓存 — 用于 _rpc_*_loop 注入 call_log
_tls = threading.local()
# 执行栈追踪（execute_code 用来读取执行完毕的 call_log）
_ACTIVE_CALL_LOG = []


def _wrap_call_log_append(call_log, tls_attr="last_tool_result"):
    """临时替 call_log.append → 注入 result 字段。"""
    real_append = call_log.append

    def _wrapped_append(item):
        if isinstance(item, dict) and "result" not in item:
            val = getattr(_tls, tls_attr, None)
            if val is not None:
                item["result"] = val
        return real_append(item)

    call_log.append = _wrapped_append
    return call_log, real_append


def apply() -> bool:
    global _applied
    if _applied:
        return True

    ok = True

    # ── P1: display._json_diff_tools 加 "execute_code" ──────────────
    try:
        import agent.display as disp
        if hasattr(disp, "_json_diff_tools"):
            s = disp._json_diff_tools
            if "execute_code" not in s:
                s.add("execute_code")
                _log.debug("display._json_diff_tools: added execute_code")
            _originals["display._json_diff_tools_set"] = True
    except ImportError:
        _log.warning("agent.display not available — skipping display patch")
        ok = False

    # ── P2: acp_adapter._format_execute_code_result 显示 diff ──────
    try:
        import acp_adapter.tools as acp
        if hasattr(acp, "_format_execute_code_result"):
            orig = acp._format_execute_code_result
            _originals["acp._format_execute_code_result"] = orig

            @functools.wraps(orig)
            def _patched_format(result):
                data = json.loads(result) if result else {}
                output = data.get("output", "")
                error = data.get("error", "")
                exit_code = data.get("exit_code")
                diff = data.get("diff", "")
                parts = [f"Exit code: {exit_code}" if exit_code is not None else "Execution complete"]
                if diff:
                    parts.extend(["", "Diff:", diff])
                if output:
                    parts.extend(["", "Output:", output])
                if error:
                    parts.extend(["", "Error:", error])
                return "\n".join(parts)

            acp._format_execute_code_result = _patched_format
    except ImportError:
        _log.warning("acp_adapter.tools not available — skipping")
        # Non-critical

    # ── P3: wrap handle_function_call 存 result ─────────────────────
    #   model_tools.handle_function_call 产 result → 存到线程局部变量
    #   _rpc_*_loop 每次调 handle_function_call 后，result 自动被缓存
    try:
        import model_tools as mt

        target = "handle_function_call"
        if hasattr(mt, target):
            _orig_hfc = getattr(mt, target)
            _originals[f"model_tools.{target}"] = _orig_hfc

            @functools.wraps(_orig_hfc)
            def _patched_hfc(tool_name, tool_args, task_id=None):
                result = _orig_hfc(tool_name, tool_args, task_id=task_id)
                _tls.last_tool_result = result
                return result

            setattr(mt, target, _patched_hfc)
        else:
            _log.warning("model_tools.%s not found", target)
            ok = False
    except Exception as e:
        _log.warning("exec_code_diff P3 failed: %s", e)
        ok = False

    # ── P4: wrap _rpc_server_loop 注入 result 到 call_log ───────────
    try:
        import tools.code_execution_tool as cet

        target = "_rpc_server_loop"
        if hasattr(cet, target):
            _orig_rsl = getattr(cet, target)
            _originals[f"cet.{target}"] = _orig_rsl

            @functools.wraps(_orig_rsl)
            def _patched_rsl(server_sock, task_id, tool_call_log,
                             tool_call_counter, max_tool_calls, allowed_tools):
                global _ACTIVE_CALL_LOG
                _ACTIVE_CALL_LOG = tool_call_log
                wrapped, real_append = _wrap_call_log_append(tool_call_log)
                try:
                    return _orig_rsl(server_sock, task_id, wrapped,
                                     tool_call_counter, max_tool_calls, allowed_tools)
                finally:
                    tool_call_log.append = real_append

            setattr(cet, target, _patched_rsl)
        else:
            _log.warning("cet.%s not found", target)
            ok = False
    except Exception as e:
        _log.warning("exec_code_diff P4 failed: %s", e)
        ok = False

    # ── P5: wrap _rpc_poll_loop 注入 result 到 call_log ─────────────
    try:
        import tools.code_execution_tool as cet

        target = "_rpc_poll_loop"
        if hasattr(cet, target):
            _orig_rpl = getattr(cet, target)
            _originals[f"cet.{target}"] = _orig_rpl

            @functools.wraps(_orig_rpl)
            def _patched_rpl(env, rpc_dir, task_id, tool_call_log,
                             tool_call_counter, max_tool_calls,
                             allowed_tools, stop_event):
                global _ACTIVE_CALL_LOG
                _ACTIVE_CALL_LOG = tool_call_log
                wrapped, real_append = _wrap_call_log_append(tool_call_log)
                try:
                    return _orig_rpl(env, rpc_dir, task_id, wrapped,
                                     tool_call_counter, max_tool_calls,
                                     allowed_tools, stop_event)
                finally:
                    tool_call_log.append = real_append

            setattr(cet, target, _patched_rpl)
        else:
            _log.warning("cet.%s not found (Docker mode only)", target)
            # non-critical — _rpc_server_loop handles local mode
    except Exception as e:
        _log.warning("exec_code_diff P5 failed: %s", e)
        # non-critical

    # ── P6: wrap execute_code 提 diff 到 result ─────────────────────
    try:
        import tools.code_execution_tool as cet

        target = "execute_code"
        if hasattr(cet, target):
            _orig_ec = getattr(cet, target)
            _originals[f"cet.{target}"] = _orig_ec

            @functools.wraps(_orig_ec)
            def _patched_ec(code, task_id=None, enabled_tools=None):
                global _ACTIVE_CALL_LOG
                _ACTIVE_CALL_LOG = []
                result_json = _orig_ec(code, task_id=task_id, enabled_tools=enabled_tools)

                # Promote diffs from _ACTIVE_CALL_LOG
                if _ACTIVE_CALL_LOG:
                    try:
                        result = json.loads(result_json) if isinstance(result_json, str) else result_json
                        if isinstance(result, dict):
                            diffs = []
                            for entry in _ACTIVE_CALL_LOG:
                                raw = entry.get("result", "{}")
                                try:
                                    cr = json.loads(raw) if isinstance(raw, str) else (raw or {})
                                    if cr.get("diff"):
                                        diffs.append(cr["diff"])
                                except Exception:
                                    pass
                            if diffs:
                                result["diff"] = "\n".join(diffs)
                                result_json = json.dumps(result)
                    except Exception:
                        pass

                return result_json

            setattr(cet, target, _patched_ec)
        else:
            _log.warning("cet.%s not found", target)
            ok = False
    except Exception as e:
        _log.warning("exec_code_diff P6 failed: %s", e)
        ok = False

    _applied = ok
    return ok


def revert():
    global _applied

    # P6: execute_code
    key = "cet.execute_code"
    if key in _originals:
        try:
            import tools.code_execution_tool as cet
            cet.execute_code = _originals[key]
        except Exception:
            pass

    # P5: _rpc_poll_loop
    key = "cet._rpc_poll_loop"
    if key in _originals:
        try:
            import tools.code_execution_tool as cet
            cet._rpc_poll_loop = _originals[key]
        except Exception:
            pass

    # P4: _rpc_server_loop
    key = "cet._rpc_server_loop"
    if key in _originals:
        try:
            import tools.code_execution_tool as cet
            cet._rpc_server_loop = _originals[key]
        except Exception:
            pass

    # P3: model_tools.handle_function_call
    key = "model_tools.handle_function_call"
    if key in _originals:
        try:
            import model_tools as mt
            mt.handle_function_call = _originals[key]
        except Exception:
            pass

    # P2: acp
    key = "acp._format_execute_code_result"
    if key in _originals:
        try:
            import acp_adapter.tools as acp
            acp._format_execute_code_result = _originals[key]
        except Exception:
            pass

    # P1: display
    if "display._json_diff_tools_set" in _originals:
        try:
            import agent.display as disp
            if hasattr(disp, "_json_diff_tools"):
                disp._json_diff_tools.discard("execute_code")
        except Exception:
            pass

    _originals.clear()
    _applied = False


def is_applied() -> bool:
    return _applied
