"""Nija 策略插件——框架级工具拦截 + 记忆交叉验证。

在 Hermes 原生 pre_tool_call 钩子上挂载。
规则在 config.yaml，记忆在 ~/.hermes/memories/。

架构:
  工具调用 → pre_tool_call hook
    ├── 查 config.yaml 静态规则
    ├── 查 MEMORY.md 动态冲突
    ├── 查 FAILURES.md 历史模式
    └── 命中 → block
"""
import os
import re
import fnmatch
import subprocess
from typing import Optional, Dict, Any

MEMORIES = os.path.expanduser("~/.hermes/memories")


def _grep_memory(keyword: str) -> str:
    """搜索所有记忆文件，返回匹配行"""
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


def _load_rules() -> list:
    import yaml
    try:
        with open(os.path.expanduser("~/.hermes/config.yaml")) as f:
            cfg = yaml.safe_load(f)
    except Exception:
        return []
    policy = cfg.get("pre_tool_policy", {})
    if not policy.get("enabled"):
        return []
    return policy.get("rules", [])


def _match_static(tool_name: str, args: dict, rule: dict) -> Optional[str]:
    """匹配 config.yaml 静态规则"""
    if rule.get("tool") and rule["tool"] != tool_name:
        return None
    pattern = rule.get("pattern", "*")
    if pattern == "*":
        return rule.get("message", f"Blocked by policy: {tool_name}")
    arg_str = str(args)
    if fnmatch.fnmatch(arg_str, pattern) or re.search(pattern, arg_str):
        return rule.get("message", f"Blocked by policy: {tool_name}")
    return None


def _check_memory_conflict(tool_name: str, args: dict) -> Optional[str]:
    """动态查记忆——配置变更冲突检测"""
    if tool_name != "terminal":
        return None
    cmd = args.get("command", "")
    if "config set" not in cmd and "config.yaml" not in cmd:
        return None

    # 提取关键词搜索记忆
    keywords = re.findall(r'config set (\S+)', cmd)
    if not keywords:
        keywords = re.findall(r'(\S+\.\S+)', cmd)
    keyword = " ".join(keywords) if keywords else cmd

    hits = _grep_memory(keyword)
    if not hits:
        hits = _grep_memory(cmd.split()[-1] if cmd.split() else "")

    if hits:
        return f"⛔ 记忆冲突:\n{hits[:500]}\n\n请确认后再执行。"
    return None


def _check_document_safety(tool_name: str, args: dict) -> Optional[str]:
    """文档编辑安全——P0 协议验证"""
    if tool_name not in ("patch", "write_file"):
        return None
    path = args.get("path", args.get("file_path", ""))
    if not path or ".md" not in path:
        return None
    # 阻止任何不先 read_file 的文档编辑
    return (
        f"⛔ P0 文档编辑协议:\n"
        f"  1. read_file {path} 全篇\n"
        f"  2. 执行修改\n"
        f"  3. read_file 验证无行丢失\n"
        f"  4. diff 确认\n"
        f"是否已执行 Step 1?"
    )


def on_pre_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Optional[Dict[str, str]]:
    args = args if isinstance(args, dict) else {}

    # 1. 静态规则
    for rule in _load_rules():
        msg = _match_static(tool_name, args, rule)
        if msg:
            return {"action": "block", "message": msg}

    # 2. 动态记忆冲突
    msg = _check_memory_conflict(tool_name, args)
    if msg:
        return {"action": "block", "message": msg}

    # 3. 文档安全
    msg = _check_document_safety(tool_name, args)
    if msg:
        return {"action": "block", "message": msg}

    return None
