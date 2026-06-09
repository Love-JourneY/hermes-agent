"""Nija 策略插件——三层拦截 + 记忆联动 + 技能追踪。

钩子:
  pre_llm_call      → 注入强制上下文 + 检测上轮是否调了技能
  pre_tool_call     → 工具调用前硬拦
  post_tool_call    → 工具调用后自检 + 追踪 skill_view 调用
"""
import os
import re
import subprocess
from typing import Optional, Dict, Any

MEMORIES = os.path.expanduser("~/.hermes/memories")

# 跨轮状态追踪
_skills_loaded_this_turn = False


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
    global _skills_loaded_this_turn

    failures = _load_recent_failures()
    rules = _load_critical_rules()

    # 构建上下文
    context = (
        "⚠️ 回复前必须检查:\n"
        "1. 这是凭感觉还是查了文件?\n"
        "2. 这次回复是否在重复已知失败模式?\n"
        "3. 需要改配置/改文档吗? → 先过 P0 协议\n"
        "4. 中型以上任务? → 先查官方文档\n"
        "5. Nija 想要选项吗? → 给 A/B/C\n\n"
    )

    # 上轮没调技能 → 升级为硬性要求
    if not _skills_loaded_this_turn:
        context = (
            "⛔ 本轮强制: 回复前先调 skill_view 检查是否有匹配技能。"
            "185个技能不是摆设。F8/F9 教训在此。\n\n"
        ) + context
    else:
        context = (
            "✅ 上轮已调技能, 保持。\n\n"
        ) + context

    if failures:
        context += f"最近失败记录:\n{failures[:1000]}\n\n"
    if rules:
        context += f"负面规则:\n{rules[:1000]}\n\n"
    context += "---\n"

    # 重置本轮的追踪
    _skills_loaded_this_turn = False

    return {"context": context}


def on_pre_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Optional[Dict[str, str]]:
    args = args if isinstance(args, dict) else {}

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
    global _skills_loaded_this_turn

    args = args if isinstance(args, dict) else {}

    # 追踪技能调用
    if tool_name in ("skill_view", "skills_list", "skill_manage"):
        _skills_loaded_this_turn = True

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
