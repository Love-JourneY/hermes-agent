"""Nija 策略插件——事前拦截 + 事后验证 + 记忆联动。

官方钩子:
  pre_tool_call  → 事前硬拦
  post_tool_call → 事后自检（官方文档确认的钩子）

规则来源: ~/.hermes/memories/{MEMORY,FAILURES,DONT_DO}.md
"""
import os
import re
import subprocess
from typing import Optional, Dict, Any

MEMORIES = os.path.expanduser("~/.hermes/memories")


def _grep_memory(keyword: str) -> str:
    try:
        result = subprocess.run(
            ["grep", "-ih", keyword,
             f"{MEMORIES}/MEMORY.md",
             f"{MEMORIES}/FAILURES.md",
             f"{MEMORIES}/DONT_DO.md"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return ""


def on_pre_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Optional[Dict[str, str]]:
    args = args if isinstance(args, dict) else {}

    # 文档安全——事前提醒
    if tool_name in ("patch", "write_file"):
        path = args.get("path", args.get("file_path", ""))
        if path and ".md" in path:
            return {
                "action": "block",
                "message": (
                    f"⛔ P0 文档编辑协议:\n"
                    f"  1. read_file {path} 全篇记行数\n"
                    f"  2. 执行修改\n"
                    f"  3. read_file 验证无行丢失\n"
                    f"  4. diff 确认\n"
                    f"Step 1 执行了吗?"
                ),
            }

    # 记忆冲突——配置变更
    if tool_name == "terminal":
        cmd = args.get("command", "")
        if "config set" in cmd or "config.yaml" in cmd:
            keywords = re.findall(r'config set (\S+)', cmd)
            keyword = " ".join(keywords) if keywords else cmd.split()[-1] if cmd.split() else cmd
            hits = _grep_memory(keyword)
            if hits:
                return {
                    "action": "block",
                    "message": f"⛔ 记忆冲突:\n{hits[:500]}\n\n请确认后再执行。",
                }

    return None


def on_post_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    result: Optional[str] = None,
    **kwargs,
) -> Optional[str]:
    args = args if isinstance(args, dict) else {}

    # 文档编辑后——验证行数
    if tool_name in ("patch", "write_file"):
        path = args.get("path", args.get("file_path", ""))
        if path and ".md" in path and os.path.exists(path):
            try:
                with open(path) as f:
                    lines = len(f.readlines())
                if result:
                    return f"{result}\n\n📋 自检: {path} 当前 {lines} 行。请 read_file 验证。"
            except Exception:
                pass

    return None


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
