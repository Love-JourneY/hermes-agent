"""
hermes-local-patches — 所有 Hermes 本地热补丁的纯 monkey-patch 实现

原理
====
运行时替换目标 Python 函数，不修改任何源文件。
跨进程：.pth 文件注入 ACP 子进程 → patch_loader → apply 全部模块。
CLI 进程：register() 直接 apply。

升级上游：git pull → restart gateway → 自动适应。
"""

import atexit
import logging
import os

_log = logging.getLogger("hermes-local-patches")

from . import loader

# .pth 文件路径 — ACP 子进程启动时自动加载 patch_loader
_PTH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "venv", "lib", "python3.11", "site-packages",
    "hermes-local-patches.pth",
)
# NOTE: .pth 文件每行是一条 import 语句。Python site.py 逐行 exec。
# 不能有末尾 \\n 转义序列 — site.py 会把 \\ 当作行继续符导致 SyntaxError。
_PTH_CONTENT = (
    "import sys; sys.path.insert(0, '{}'); "
    "from patch_loader import load; load()"
).format(os.path.dirname(os.path.abspath(__file__)).replace("'", "\\'"))


def _write_pth():
    """写入 .pth 文件，确保 ACP 子进程启动时加载 patch_loader。"""
    try:
        os.makedirs(os.path.dirname(_PTH_PATH), exist_ok=True)
        with open(_PTH_PATH, "w") as f:
            f.write(_PTH_CONTENT)
        _log.warning("DIAG: .pth written to %s", _PTH_PATH)
    except Exception as e:
        _log.warning("DIAG: .pth write failed: %s", e)


def _remove_pth():
    """删除 .pth 文件。"""
    try:
        if os.path.exists(_PTH_PATH):
            os.remove(_PTH_PATH)
            _log.warning("DIAG: .pth removed")
    except Exception as e:
        _log.warning("DIAG: .pth remove failed: %s", e)


def _cleanup():
    """进程退出时 revert 所有模块 + 删除 .pth。"""
    loader.revert_all()
    _remove_pth()


def register(ctx):
    # 0. 写入 .pth 文件（跨 ACP 子进程生效）
    _write_pth()

    # 1. 发现并加载所有模块
    loader.discover()

    # 2. 依次 apply
    ok, fail = loader.apply_all()
    summary = loader.get_summary()

    # 3. 向 plugin-health-monitor 报告
    try:
        _pdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _state = os.path.join(_pdir, "plugin-health-monitor", "state.json")
        import json
        if os.path.exists(_state):
            with open(_state) as f:
                st = json.load(f)
        else:
            st = {}
        st["hermes-local-patches"] = {
            "status": "ok" if fail == 0 else "degraded",
            "message": summary,
            "updated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        }
        os.makedirs(os.path.dirname(_state), exist_ok=True)
        with open(_state, "w") as f:
            json.dump(st, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass

    # 4. atexit 自动恢复
    atexit.register(_cleanup)

    _log.warning("DIAG: hermes-local-patches registered ✅ (%d ok, %d failed)", ok, fail)
