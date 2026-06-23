"""write_file_diff — monkey-patch write_file TUI 红绿 diff 渲染

P1: monkey-patch ShellFileOperations.write_file — 生成 _unified_diff
P2: monkey-patch WriteResult.to_dict — 把 _ws_diff 输出为 diff 字段
P3: monkey-patch display.extract_edit_diff — 处理 write_file 的 diff
P4: monkey-patch acp_adapter.tools._format_edit_result — 显示 diff
"""

import logging
import functools

NAME = "write_file_diff"
DESCRIPTION = "write_file TUI 红绿 diff 渲染（纯 monkey-patch，零源码修改）"

_log = logging.getLogger("hermes-local-patches")

_originals = {}
_applied = False


def apply() -> bool:
    global _applied
    if _applied:
        return True

    ok = True

    # ── P1: monkey-patch ShellFileOperations.write_file ──────────────
    try:
        from tools.file_operations import ShellFileOperations, _strip_bom

        _orig_write = ShellFileOperations.write_file
        _originals["ShellFileOperations.write_file"] = _orig_write

        @functools.wraps(_orig_write)
        def _patched_write(self, path, content):
            """Wrap write_file: 调原方法后, 自己生成 diff 挂到返回值上."""
            # 1) read pre_content
            pre_content = None
            try:
                import os
                expanded = self._expand_path(path)
                if os.path.exists(expanded):
                    rc = "cat " + self._escape_shell_arg(path) + " 2>/dev/null"
                    rr = self._exec(rc)
                    if rr.exit_code == 0 and rr.stdout:
                        pre_content, _ = _strip_bom(rr.stdout)
            except Exception:
                pass

            # 2) call original write_file
            result = _orig_write(self, path, content)

            # 3) generate diff -> side channel _ws_diff
            if pre_content is not None and not result.error:
                try:
                    diff = self._unified_diff(pre_content, content, path)
                    if diff:
                        object.__setattr__(result, "_ws_diff", diff)
                except Exception:
                    pass

            return result

        ShellFileOperations.write_file = _patched_write

    except Exception as e:
        _log.warning("write_file_diff P1 failed: %s", e)
        ok = False

    # ── P2: monkey-patch WriteResult.to_dict ──────────────────────────
    try:
        from tools.file_operations import WriteResult

        _orig_to_dict = WriteResult.to_dict
        _originals["WriteResult.to_dict"] = _orig_to_dict

        @functools.wraps(_orig_to_dict)
        def _patched_to_dict(self):
            d = _orig_to_dict(self)
            d.pop("_ws_diff", None)      # clean internal attr
            _d = getattr(self, "_ws_diff", "")
            if _d:
                d["diff"] = _d
            return d

        WriteResult.to_dict = _patched_to_dict

    except Exception as e:
        _log.warning("write_file_diff P2 failed: %s", e)
        ok = False

    # ── P3: monkey-patch display.extract_edit_diff ────────────────────
    # _json_diff_tools is a LOCAL variable inside extract_edit_diff (L408),
    # not a module attribute. Must wrap the function itself.
    try:
        import agent.display as disp

        target = "extract_edit_diff"
        if hasattr(disp, target):
            _orig_extract = getattr(disp, target)
            _originals[f"display.{target}"] = _orig_extract

            @functools.wraps(_orig_extract)
            def _patched_extract(tool_name, result, **kw):
                # write_file: read result["diff"] directly
                if tool_name == "write_file" and result:
                    import json as _j
                    try:
                        _data = _j.loads(result) if isinstance(result, str) else result
                        if isinstance(_data, dict):
                            _diff = _data.get("diff")
                            if isinstance(_diff, str) and _diff.strip():
                                return _diff
                    except Exception:
                        pass
                # everything else -> original logic
                return _orig_extract(tool_name, result, **kw)

            setattr(disp, target, _patched_extract)
        else:
            _log.warning("display.%s not found", target)
            ok = False

    except ImportError:
        _log.warning("agent.display not available — P3 deferred")
    except Exception as e:
        _log.warning("write_file_diff P3 failed: %s", e)
        ok = False

    # ── P4: monkey-patch acp_adapter.tools._format_edit_result ────────
    # ACP channel also shows diff text
    try:
        import acp_adapter.tools as acp
        import json

        target = "_format_edit_result"
        if hasattr(acp, target):
            _orig_fmt = getattr(acp, target)
            _originals[f"acp.{target}"] = _orig_fmt

            @functools.wraps(_orig_fmt)
            def _patched_fmt(tool_name, result, args):
                text = _orig_fmt(tool_name, result, args)
                if tool_name == "write_file" and result:
                    try:
                        data = json.loads(result) if isinstance(result, str) else result
                        if isinstance(data, dict):
                            diff = data.get("diff", "")
                            if isinstance(diff, str) and diff.strip():
                                lines = diff.strip().split("\n")
                                preview = "\n".join(lines[:15])
                                if len(lines) > 15:
                                    preview += f"\n... ({len(lines)} lines total)"
                                text = (text or "") + "\n\nDiff:\n" + preview
                    except Exception:
                        pass
                return text

            setattr(acp, target, _patched_fmt)
        else:
            _log.warning("acp.%s not found", target)
    except ImportError:
        _log.warning("acp_adapter.tools not available — P4 skipped")
    except Exception as e:
        _log.warning("write_file_diff P4 failed: %s", e)

    _applied = ok
    return ok


def revert():
    global _applied

    # P3: display.extract_edit_diff
    key = "display.extract_edit_diff"
    if key in _originals:
        try:
            import agent.display as disp
            setattr(disp, "extract_edit_diff", _originals[key])
        except Exception:
            pass

    # P4: acp._format_edit_result
    key = "acp._format_edit_result"
    if key in _originals:
        try:
            import acp_adapter.tools as acp
            acp._format_edit_result = _originals[key]
        except Exception:
            pass

    # P2: WriteResult.to_dict
    key = "WriteResult.to_dict"
    if key in _originals:
        try:
            from tools.file_operations import WriteResult
            WriteResult.to_dict = _originals[key]
        except Exception:
            pass

    # P1: ShellFileOperations.write_file
    key = "ShellFileOperations.write_file"
    if key in _originals:
        try:
            from tools.file_operations import ShellFileOperations
            ShellFileOperations.write_file = _originals[key]
        except Exception:
            pass

    _originals.clear()
    _applied = False


def is_applied() -> bool:
    return _applied
