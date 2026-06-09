"""Nija 策略插件——渐进信任模型 + 多级闸门。

每轮不调技能/不联网 → 工具权限收紧一级：
  L1: terminal/patch/write_file/delegate_task blocked
  L2: + read_file/search_files blocked
  L3: + ALL tools blocked（软禁）

调了 skill_view 或 web_search → 权限恢复全开。
"""
import os
import re
import subprocess
from typing import Optional, Dict, Any

MEMORIES = os.path.expanduser("~/.hermes/memories")

_skills_loaded = False
_web_searched = False
_consecutive_skips = 0

# 渐进闸门
_GATED_L1 = {"terminal", "patch", "write_file", "delegate_task"}
_GATED_L2 = _GATED_L1 | {"read_file", "search_files"}
_GATED_L3 = None  # None = all tools blocked


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


def _load_recent_failures() -> str:
    try:
        with open(f"{MEMORIES}/FAILURES.md") as f:
            content = f.read()
        failures = re.findall(r'### F\d+:.*?(?=### F\d+:|$)', content, re.DOTALL)
        return "\n".join(failures[-3:]) if failures else ""
    except Exception:
        return ""


def _load_critical_rules() -> str:
    try:
        with open(f"{MEMORIES}/DONT_DO.md") as f:
            return f.read()[:2000]
    except Exception:
        return ""


def on_pre_llm_call(**kwargs) -> Optional[Dict[str, str]]:
    global _skills_loaded, _web_searched, _consecutive_skips

    failures = _load_recent_failures()
    rules = _load_critical_rules()

    # 信任模型: 每轮跳过 → 计数 +1; 调了 → 清零
    if not _skills_loaded and not _web_searched:
        _consecutive_skips += 1
    else:
        _consecutive_skips = 0

    level = min(_consecutive_skips, 3)
    if level >= 3:
        gate = (
            "🛑 软禁 L3: 已连续 3 轮不调技能/不联网。"
            "所有工具已封锁。调 skill_view 或 web_search 恢复权限。\n\n"
        )
    elif level == 2:
        gate = (
            "⛔⛔ L2 闸门: 连续 2 轮跳过。terminal/patch/write_file/read_file/search_files/delegate_task 全封锁。"
            "调 skill_view 或 web_search 恢复。\n\n"
        )
    elif level == 1:
        gate = (
            "⛔ L1 闸门: terminal/patch/write_file/delegate_task 封锁。"
            "调 skill_view 或 web_search 恢复。\n\n"
        )
    else:
        gate = "✅ 权限全开。\n\n"

    context = gate + (
        "⚠️ 回复前必须检查:\n"
        "1. 这是凭感觉还是查了文件?\n"
        "2. 这次回复是否在重复已知失败模式?\n"
        "3. 需要改配置/改文档吗? → 先过 P0 协议\n"
        "4. 中型以上任务? → 先查官方文档或联网搜索\n"
        "5. Nija 想要选项吗? → 给 A/B/C\n\n"
    )

    if failures:
        context += f"最近失败记录:\n{failures[:1000]}\n\n"
    if rules:
        context += f"负面规则:\n{rules[:1000]}\n\n"
    context += "---\n"

    _skills_loaded = False
    _web_searched = False

    return {"context": context}


def on_pre_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Optional[Dict[str, str]]:
    global _consecutive_skips
    args = args if isinstance(args, dict) else {}

    # ── 渐进闸门 ──
    level = min(_consecutive_skips, 3)

    if level >= 3:
        return {
            "action": "block",
            "message": (
                "🛑 软禁 L3: 所有工具已封锁。"
                "必须调 skill_view 或 web_search 恢复权限。"
            ),
        }
    elif level >= 2 and tool_name in _GATED_L2:
        return {
            "action": "block",
            "message": (
                f"⛔⛔ L2 闸门: {tool_name} 已封锁。"
                "先调 skill_view 或 web_search。"
            ),
        }
    elif level >= 1 and tool_name in _GATED_L1:
        return {
            "action": "block",
            "message": (
                f"⛔ L1 闸门: {tool_name} 已封锁。"
                "先调 skill_view 或 web_search。"
            ),
        }

    # ── 文档编辑 P0 ──
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

    # ── 记忆冲突 ──
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
    global _skills_loaded, _web_searched
    args = args if isinstance(args, dict) else {}

    if tool_name in ("skill_view", "skills_list", "skill_manage"):
        _consecutive_skips = 0
        _skills_loaded = True
    if tool_name in ("web_search", "web_extract", "browser_navigate"):
        _consecutive_skips = 0
        _web_searched = True

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
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
