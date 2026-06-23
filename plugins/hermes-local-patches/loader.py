"""hermes-local-patches — 模块加载器

标准模块接口（每个模块必须暴露）:
    NAME: str           — 唯一标识（如 "timeout_provider"）
    DESCRIPTION: str    — 描述
    apply() -> bool     — 应用 monkey-patch，返回是否成功
    revert() -> None    — 恢复原始函数
    is_applied() -> bool — 当前是否已 patch
"""

import logging
import os
import sys

_log = logging.getLogger("hermes-local-patches")

_modules = {}       # name → module reference
_applied = set()    # name → True 已应用
_failed = set()     # name → True 应用失败


def discover():
    """扫描 modules/ 目录，发现并导入所有模块。"""
    mod_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules")
    if not os.path.isdir(mod_dir):
        _log.warning("modules/ directory not found")
        return

    for f in sorted(os.listdir(mod_dir)):
        if f.endswith(".py") and f != "__init__.py":
            mod_name = f[:-3]
            try:
                import importlib.util
                mod_path = os.path.join(mod_dir, f)
                spec = importlib.util.spec_from_file_location(mod_name, mod_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    _modules[mod_name] = mod
                    _log.debug("discovered module: %s (%s)", mod_name, mod_path)
                else:
                    _log.warning("failed to create spec for %s", mod_name)
            except Exception as e:
                _log.warning("failed to load module %s: %s", mod_name, e)


def apply_all():
    """依次 apply 所有已发现模块。返回 (成功数, 失败数)。"""
    success = 0
    for name, mod in _modules.items():
        if name in _applied:
            success += 1
            continue
        try:
            if hasattr(mod, "apply") and callable(mod.apply):
                ok = mod.apply()
                if ok:
                    _applied.add(name)
                    _failed.discard(name)
                    _log.warning("applied: %s — %s", name, getattr(mod, "DESCRIPTION", ""))
                    success += 1
                else:
                    _failed.add(name)
                    _log.warning("FAILED: %s (apply returned False)", name)
            else:
                _log.warning("skip %s: no apply() function", name)
        except Exception as e:
            _failed.add(name)
            _log.warning("FAILED: %s — %s", name, e)
    return success, len(_modules) - success


def revert_all():
    """依次 revert 所有已应用模块。"""
    for name in list(_applied):
        mod = _modules.get(name)
        if mod and hasattr(mod, "revert"):
            try:
                mod.revert()
                _applied.discard(name)
                _log.warning("reverted: %s", name)
            except Exception as e:
                _log.warning("revert failed for %s: %s", name, e)


def status() -> dict:
    """返回所有模块的状态。"""
    result = {}
    for name, mod in _modules.items():
        applied = name in _applied
        failed = name in _failed
        desc = getattr(mod, "DESCRIPTION", "")
        result[name] = {
            "applied": applied,
            "failed": failed,
            "description": desc,
        }
    return result


def get_summary() -> str:
    """返回单行摘要供 TUI 状态栏或日志使用。"""
    total = len(_modules)
    ok = len(_applied)
    fail = len(_failed)
    if fail:
        return f"🔴 {ok}/{total} ok ({fail} failed)"
    if ok == total:
        return f"🟢 {ok}/{total} ok"
    return f"🟡 {ok}/{total} ok"
