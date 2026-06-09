"""Nija 策略插件——四层拦截 + 技能追踪 + 联网追踪。

钩子:
  pre_llm_call      → 注入强制上下文 + 检测上轮是否调了技能/联网
  pre_tool_call     → 工具调用前硬拦 (config/doc/skill-gate/search-gate)
  post_tool_call    → 追踪 skill_view + web_search 调用 + 文档行数验证
"""
import os
import re
import subprocess
from typing import Optional, Dict, Any

MEMORIES = os.path.expanduser("~/.hermes/memories")

_skills_loaded = False
_web_searched = False

# 需要前置检查的工具（调这些前必须先调技能或联网搜索）
_GATED_TOOLS = {"terminal", "patch", "write_file", "delegate_task"}


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
    global _skills_loaded, _web_searched

    failures = _load_recent_failures()
    rules = _load_critical_rules()

    # 状态提示
    if not _skills_loaded and not _web_searched:
        gate = "⛔ 本轮强制: 回复前先调 skill_view 或 web_search。185个技能不是摆设，三套联网基础设施不是装饰。F8/F9 教训在此。\n\n"
    elif not _skills_loaded:
        gate = "⚠️ 上轮没调技能。建议加载。\n\n"
    elif not _web_searched:
        gate = "⚠️ 上轮没联网搜索。中型任务建议查资料。\n\n"
    else:
        gate = "✅ 技能+联网 已覆盖, 保持。\n\n"

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
    global _skills_loaded, _web_searched
    args = args if isinstance(args, dict) else {}

    # ── 技能/联网闸门: 调 gated 工具前必须先调技能或联网 ──
    if tool_name in _GATED_TOOLS:
        if not _skills_loaded and not _web_searched:
            return {
                "action": "block",
                "message": (
                    "⛔ 技能闸门: 调 terminal/patch/write_file/delegate_task 前\n"
                    "必须先调 skill_view (加载技能) 或 web_search (联网查资料)。\n"
                    "F8/F9 教训: 185个技能 + 三套联网基础设施不是摆设。"
                ),
            }

    # ── 文档编辑 P0 协议 ──
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

    # ── 记忆冲突: 配置变更 ──
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

    # 追踪技能
    if tool_name in ("skill_view", "skills_list", "skill_manage"):
        _skills_loaded = True

    # 追踪联网搜索
    if tool_name in ("web_search", "web_extract", "browser_navigate"):
        _web_searched = True

    # 文档编辑后验证
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
