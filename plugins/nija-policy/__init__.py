"""Nija 策略插件 v2.9 — 硬闸门 + P0智能门 + 语义审计硬闸。

P0 三级:
  1. 预检: read_file 过的 .md 才放行 patch | write_file 对 .md 永久封
  2. 结构审计: patch 后自动检测行数/标题/索引/链接
  3. 语义审计: patch .md → 标记 _semantic_audit_pending → 下轮封锁直到 read_file 验证
"""

import os
import re
import subprocess
from typing import Optional, Dict, Any

MEMORIES = os.path.expanduser("~/.hermes/memories")
SKILLS = os.path.expanduser("~/.hermes/skills")
MAINTENANCE = os.path.expanduser("~/Documents/system-maintenance/MAINTENANCE.md")
HERMES_HOME = os.path.expanduser("~/.hermes")
SOUL = os.path.join(HERMES_HOME, "SOUL.md")

_skills_loaded = False
_web_searched = False
_consecutive_skips = 0
_docs_may_be_stale = False
_needs_doc_sync = False
_last_modified_doc = ""
_loaded_skills_this_turn = []
_files_read_this_turn = []
_semantic_audit_pending = False
_audit_files = []
_audit_verified = set()
_patch_warnings = []
_file_snapshots = {}
_modified_files = set()

# SKILL STATS: 追踪技能使用频率，用于 DIVERSITY GATE
_skill_usage_history = {}   # {skill_name: count_in_last_10_turns}
_recent_skills = []         # ordered list of skill names, max 10

_GATED_L1 = {"terminal", "patch", "write_file", "delegate_task"}
_GATED_L2 = _GATED_L1 | {"read_file", "search_files"}

# execute_code 独立管理——不能和 terminal/patch 一样"加载技能就解锁"
# 只有明确允许的技能（如 self-test-protocol）才能放行 execute_code
_EXECUTE_CODE_SKILLS = {"self-test-protocol"}

_DIR_SKILL_MAP = {
    "dev/": ["github-pr-workflow", "github-issues", "requesting-code-review"],
    "docker/": ["infra-healthcheck", "docker-network-bypass"],
}

# 被 patch 的文件 → 语义审计时需一起读的文件
_AUDIT_SIBLINGS = {
    "MEMORY.md": ["FAILURES.md", "DONT_DO.md", "SOUL.md"],
    "FAILURES.md": ["MEMORY.md", "DONT_DO.md"],
    "DONT_DO.md": ["FAILURES.md", "MEMORY.md"],
    "MAINTENANCE.md": ["SOUL.md"],
    "SOUL.md": ["MEMORY.md", "MAINTENANCE.md"],
}

# 解析兄弟文件路径——不在 MEMORIES 下的特殊处理
def _resolve_audit_path(sibling_name: str) -> str:
    if sibling_name in ("SOUL.md",): return SOUL
    if sibling_name in ("MAINTENANCE.md",): return MAINTENANCE
    return os.path.join(MEMORIES, sibling_name)


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


def on_pre_llm_call(**kwargs) -> Optional[Dict[str, str]]:
    global _skills_loaded, _web_searched, _consecutive_skips
    global _needs_doc_sync, _last_modified_doc
    global _loaded_skills_this_turn, _files_read_this_turn
    global _semantic_audit_pending, _audit_files, _patch_warnings, _audit_verified, _file_snapshots, _modified_files

    # 自评估（非关键词——上一轮的 self-rating）

    if not _skills_loaded and not _web_searched:
        _consecutive_skips += 1
    else:
        _consecutive_skips = 0

    _loaded_skills_this_turn = []
    _files_read_this_turn = []

    cwd = os.getcwd()

    gate_msg = (
        "🔒 HARD GATE — 工具封锁。你必须先完成:\\n"
        "1. 反思: 我们现在在做什么任务？(一句话)\\n"
        "2. 任务类型: GitHub/调试/配置/设计/测试/插件开发/研究/文档同步/其他\\n"
        "3. 根据类型，判断应加载哪些技能→skill_view 加载\\n"
        "4. 工具自动解锁\\n"
        f"📂 当前目录: {cwd}\\n"
        "💡 不要等 Nija 提醒。你的反思是你的触发词。\\n\\n"
        "5. 自评: 上轮回复是[A]行动 [B]分析 [C]文字？对自己上轮打分: 有效/还行/在哄\\n\\n"
    )


    # 结构审计警告（上轮 patch 的结果）
    struct_warn = ""
    if _patch_warnings:
        struct_warn = "⚠️ P0 结构审计:\\n" + "\\n".join(_patch_warnings[-5:]) + "\\n\\n"
        _patch_warnings = []

    # 语义审计硬闸
    audit_gate = ""
    if _semantic_audit_pending:
        remaining = [f for f in _audit_files if f not in _files_read_this_turn]
        if remaining:
            audit_gate = (
                "🔒 SEMANTIC AUDIT REQUIRED — 工具封锁。\\n"
                f"上次修改了文档，必须 read_file 验证:\\n"
                + "".join(f"  → {f}\\n" for f in _audit_files)
                + f"还剩 {len(remaining)} 个未验证。工具封锁直到全部 read_file。\\n\\n"
            )

    stale = ""
    global _docs_may_be_stale
    if _docs_may_be_stale:
        stale = "📋 代码已变更，检查文档是否需要更新。\\n\\n"
        _docs_may_be_stale = False

    doc_sync = ""
    if _needs_doc_sync:
        doc_sync = (
            "🔒 FORCED DOC-SYNC\\n"
            f"上次修改了: {_last_modified_doc}\\n"
            "→ 必须完成五层文档同步 再继续\\n\\n"
        )
        _needs_doc_sync = False

    memory_check = ""
    recent = _grep_memory("F9|F10|F11|F12|F13|F14")
    if recent:
        memory_check = f"⚠️ 近期失败（别重复）:\\n{recent[:300]}\\n\\n"

    context = gate_msg + audit_gate + struct_warn + doc_sync + stale + memory_check + "---\\n"

    _skills_loaded = False
    _web_searched = False

    return {"context": context}


def on_pre_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Optional[Dict[str, str]]:
    global _consecutive_skips, _loaded_skills_this_turn, _files_read_this_turn
    global _semantic_audit_pending, _audit_files
    global _skill_usage_history, _recent_skills
    args = args if isinstance(args, dict) else {}

    level = min(_consecutive_skips, 3)

    # ── execute_code 独立闸门 ──
    # 不在 GATED_L1 中——不能靠"加载任意技能"就解锁
    # 只在加载 self-test-protocol 等明确允许的技能后才放行
    if tool_name == "execute_code":
        allowed = _loaded_skills_this_turn and any(
            s in _EXECUTE_CODE_SKILLS for s in _loaded_skills_this_turn
        )
        if not allowed:
            return {
                "action": "block",
                "message": (
                    f"🔒 EXECUTE_CODE 封锁。\\\\n"
                    "execute_code 绕过了所有审计门（terminal/patch/write_file 的闸对它不起作用）。\\\\n"
                    "要解锁: skill_view('self-test-protocol') 确认你正在验证自建系统。\\\\n"
                    "其他场景: 用 terminal 运行 Python 脚本文件，不要用 execute_code。"
                ),
            }

    # ── HARD GATE: 未加载技能就封锁 ──
    if tool_name in _GATED_L1 and not _loaded_skills_this_turn:
        return {
            "action": "block",
            "message": (
                f"🔒 HARD GATE: {tool_name} 封锁。\n"
                "你必须先反思当前任务→判断类型→加载匹配技能。\n"
                "确定类型后，skill_view 加载对应技能即可解锁"
            ),
        }

    # ── SKILL STATS GATE: 技能多样性硬约束 ──
    if tool_name in _GATED_L1 and _loaded_skills_this_turn:
        # 检查最近10次中任一技能出现≥3次 → 过度依赖
        for skill in _loaded_skills_this_turn:
            count = _skill_usage_history.get(skill, 0)
            if count >= 3:
                return {
                    "action": "block",
                    "message": (
                        f"🔒 SKILL STATS: {skill} 在最近10次中用了{count}次——过度依赖。\n"
                        "要解锁: 加载一个最近没用过的不同类别技能。\n"
                        "提示: skills_list 看全量→选不常用的→skill_view 加载。"
                    ),
                }

    # ── 语义审计硬闸 ──
    if _semantic_audit_pending and tool_name in _GATED_L1:
        remaining = [f for f in _audit_files if f not in _files_read_this_turn]
        if remaining:
            return {
                "action": "block",
                "message": (
                    f"🔒 SEMANTIC AUDIT: {tool_name} 封锁。\\n"
                    f"还剩 {len(remaining)} 个文件未验证: {', '.join(remaining)}\\n"
                    f"→ read_file 逐个验证 → 全部读完后自动解锁"
                ),
            }

    # ── 文件修改硬闸 ──
    if tool_name in _GATED_L1 and _modified_files:
        recent = sorted(_modified_files)[-6:]
        return {
            "action": "block",
            "message": (
                f"🔒 FILE MODIFIED: {tool_name} 封锁。\\n"
                f"检测到 {len(_modified_files)} 个文件被修改:\\n"
                + "\\n".join(f"  → {f}" for f in recent)
                + f"\\n→ read_file 逐个审计 → 全部验证后解锁"
            ),
        }

    # ── 渐进闸门 ──
    if level >= 3:
        return {"action": "block", "message": "🛑 软禁 L3。"}
    elif level >= 2 and tool_name in _GATED_L2:
        return {"action": "block", "message": f"⛔⛔ L2: {tool_name} 封锁。先调 skill_view。"}

    # ── 文档编辑 P0（智能门）──
    if tool_name == "write_file":
        path = args.get("path", args.get("file_path", ""))
        if path and ".md" in path:
            return {
                "action": "block",
                "message": (
                    f"⛔ P0: write_file 覆盖整个 {path} ——无 diff 审计。\\n"
                    "write_file 对 .md 永久封锁。请用 patch（有红绿 diff）。"
                ),
            }

    # ── execute_code 代码修改闸 ──
    if tool_name == "execute_code":
        py_code = args.get("code", "")
        src_exts = (".py", ".md", ".yaml", ".sh", ".json")
        write_ops = ("open(", "write(", "write_file", ".write(", "path.write")
        if any(ext in py_code for ext in src_exts) and any(op in py_code for op in write_ops):
            return {
                "action": "block",
                "message": (
                    "⛔ P0: execute_code 正在写入代码文件。\\n"
                    "改代码必须用 patch（有红绿 diff，Nija 可审计）。\\n"
                    "流程: read_file→patch→verify→pyc清→/exit"
                ),
            }

    if tool_name == "patch":
        path = args.get("path", args.get("file_path", ""))
        if path and ".md" in path:
            norm = os.path.normpath(os.path.expanduser(path)) if path else ""
            if norm not in _files_read_this_turn:
                return {
                    "action": "block",
                    "message": (
                        f"⛔ P0: 还没 read_file {path}\\n"
                        "→ read_file 全篇记行数 → patch → read_file 验证行数≥改前"
                    ),
                }

    # ── 记忆冲突 ──
    if tool_name == "terminal":
        cmd = args.get("command", "")
        if any(kw in cmd for kw in ("config set", "config.yaml", "hermes config", "mv ~", "rm -rf ~")):
            hits = _grep_memory(cmd.split()[-1] if cmd.split() else cmd)
            if hits:
                return {"action": "block", "message": f"⛔ 记忆冲突:\\n{hits[:500]}\\n\\n确认后再执行。"}

    return None


def on_post_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    result: Optional[str] = None,
    **kwargs,
) -> Optional[str]:
    global _skills_loaded, _web_searched, _consecutive_skips, _loaded_skills_this_turn
    global _needs_doc_sync, _last_modified_doc, _files_read_this_turn
    global _semantic_audit_pending, _audit_files, _patch_warnings, _audit_verified, _file_snapshots, _modified_files
    global _skill_usage_history, _recent_skills
    args = args if isinstance(args, dict) else {}

    if tool_name == "read_file":
        path = args.get("path", "")
        if path:
            norm = os.path.normpath(os.path.expanduser(path))
            if norm not in _files_read_this_turn:
                _files_read_this_turn.append(norm)
            # 读 .md → 存快照用于 patch 后语义比较
            if norm.endswith('.md'):
                try:
                    with open(norm) as f:
                        lines = f.read().splitlines()
                    _file_snapshots[norm] = {
                        'titles': {l for l in lines if l.startswith('###')},
                        'list_items': {l for l in lines if l.startswith(('- ', '* ', '+ '))},
                        'dates': len([l for l in lines if '[日期]' in l]),
                        'line_count': len(lines)
                    }
                except: pass
            # 清除已读的修改文件
            if norm in _modified_files:
                _modified_files.discard(norm)
            # 语义审计: 全部读完 → 清除标记
            if _semantic_audit_pending and _audit_files:
                _audit_verified.add(norm)
                if _audit_verified.issuperset(_audit_files):
                    _semantic_audit_pending = False
                    _audit_files = []
                    _audit_verified = set()

    # 文档修改检测 → doc_sync
    if tool_name in ("skill_manage", "write_file", "patch", "execute_code", "cronjob"):
        path = args.get("path", args.get("file_path", ""))
        code_arg = args.get("code", "")
        trig = ("plugins/", "skills/", "config.yaml", ".env", "scripts/",
                "MAINTENANCE.md", "notes/", "SOUL.md", "MEMORY.md", "FAILURES.md", "DONT_DO.md")
        if any(kw in (path or "") for kw in trig) or (".md" in code_arg and any(kw in code_arg for kw in trig)):
            _needs_doc_sync = True
            _last_modified_doc = path or "execute_code .md write"

    # patch 后结构审计
    if tool_name == "patch":
        path = args.get("path", args.get("file_path", ""))
        if path and ".md" in path:
            full = os.path.normpath(os.path.expanduser(path))
            try:
                with open(full) as f:
                    content = f.read()
                    lines = content.splitlines()
                title_count = len([l for l in lines if l.startswith('###')])
                list_count = len([l for l in lines if l.startswith(('- ', '* ', '+ '))])
                date_count = len([l for l in lines if '[日期]' in l])

                base = os.path.basename(full)
                summary = f"{base}: {len(lines)}行, {title_count}标题, {list_count}列表, {date_count}日期"

                # 行数减少 = 警告
                _patch_warnings.append(summary)
                
                # 语义比较: 和读时快照对比
                snap = _file_snapshots.pop(full, None)
                if snap:
                    lost_titles = snap['titles'] - {l for l in lines if l.startswith('###')}
                    lost_items = snap['list_items'] - {l for l in lines if l.startswith(('- ', '* ', '+ '))}
                    if lost_titles:
                        _patch_warnings.append(f"⚠️ {base}: {len(lost_titles)}标题消失!")
                    if lost_items:
                        _patch_warnings.append(f"⚠️ {base}: {len(lost_items)}列表条目消失!")
            except Exception:
                pass

            # 语义审计标记
            _semantic_audit_pending = True
            _audit_verified = set()
            base = os.path.basename(full)
            _audit_files = [full]  # 被改的文件必须读
            for key, siblings in _AUDIT_SIBLINGS.items():
                if key in full:
                    for sib in siblings:
                        sib_path = _resolve_audit_path(sib)
                        if sib_path not in _audit_files:
                            _audit_files.append(sib_path)
                    break

    # ── 全机文件修改检测 ──
    if tool_name in ("terminal", "patch", "write_file", "execute_code"):
        try:
            home = os.path.expanduser("~")
            result = subprocess.run(
                f"find {home} -maxdepth 4 -mmin -1 -not -path '*/.cache/*' -not -path '*/.local/*' "
                f"-not -path '*/node_modules/*' -not -path '*/__pycache__/*' "
                f"-not -path '*/.git/*' -not -path '*/Downloads/*' "
                f"-not -path '*/Backups/*' -not -path '*/.*' -type f 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().split('\n'):
                if line:
                    _modified_files.add(line)
        except: pass

    if tool_name in ("skill_view", "skills_list", "skill_manage"):
        _consecutive_skips = 0
        _skills_loaded = True
        skill_name = args.get("name", "")
        if skill_name and skill_name not in _loaded_skills_this_turn:
            _loaded_skills_this_turn.append(skill_name)
            # SKILL STATS 追踪
            _recent_skills.append(skill_name)
            if len(_recent_skills) > 10:
                old = _recent_skills.pop(0)
                _skill_usage_history[old] = _skill_usage_history.get(old, 0) - 1
            _skill_usage_history[skill_name] = _skill_usage_history.get(skill_name, 0) + 1

    if tool_name in ("web_search", "web_extract", "browser_navigate"):
        _consecutive_skips = 0
        _web_searched = True

    return None


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
