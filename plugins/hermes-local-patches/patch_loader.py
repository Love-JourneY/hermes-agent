"""patch_loader — .pth 文件入口，ACP 子进程启动时自动执行

被 venv/lib/python3.11/site-packages/hermes-local-patches.pth 引用。
ACP 子进程 Python 启动 → .pth 执行 → 本模块加载 → 所有模块 apply()
"""

import importlib.util
import logging
import os
import sys

_log = logging.getLogger("hermes-local-patches")

_MOD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules")


def load():
    """加载并 apply 全部模块。被 .pth 文件调用。异常安全。"""
    if not os.path.isdir(_MOD_DIR):
        return

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    for f in sorted(os.listdir(_MOD_DIR)):
        if f.endswith(".py") and f != "__init__.py":
            mod_name = f[:-3]
            mod_path = os.path.join(_MOD_DIR, f)
            try:
                spec = importlib.util.spec_from_file_location(mod_name, mod_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    if hasattr(mod, "apply") and callable(mod.apply):
                        mod.apply()
            except Exception:
                pass


def load_safe():
    """异常安全的 load 封装。被 .pth 文件调用。"""
    try:
        load()
    except Exception:
        pass
