"""Nija 策略插件 v4.5 — 硬闸门 + P0智能门 + 语义审计 + 全读闸门 + 覆盖率闸门 + SKILL STATS v4.1 + 框架工具闸门 + 源码闭环审计 + 内容相同豁免。

P0 三级:
  1. 预检: read_file 过的 .md 才放行 patch | write_file 对 .md 永久封
  2. 结构审计: patch 后自动检测行数/标题/索引/链接
  3. 语义审计: patch .md → 标记 _semantic_audit_pending → 下轮封锁直到 read_file 验证

v3.8 双闸门:
  4. 全读闸门: patch/write_file 前必须本回合读过全文件
  5. 覆盖率闸门: patch 的 old_string 目标行必须在 read 覆盖范围内
  
v4.1 回合边界冷却:
  6. SKILL STATS GATE 只检查上回合技能——本回合永放行。鼓励单回合长任务。

v4.2 框架工具闸门:
  7. terminal curl localhost:3002 → 🔒 → web_search/web_extract
     terminal curl localhost:8080 → 🔒 → browser_navigate

v4.3 源码闭环审计:
  8. 源码文件(.py/.md/.yaml等)被terminal修改→ FILE MODIFIED 锁
     → read_file 不解锁 → 必须用 patch 记录变更 → 自动解锁
     非源码文件(jobs.json/memo.md) read_file 即解锁"""

import os
import re
import subprocess
import time
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
_skills_loaded_last_turn = []  # v4.1: 上回合的技能（回合边界冷却检查）
_files_read_this_turn: Dict[str, Dict] = {}  # v3.8: {path: {"ranges":[(s,e)], "total_lines":N, "read_full":bool}}
_semantic_audit_pending = False
_audit_files = []
_audit_verified = set()
_patch_warnings = []
_file_snapshots = {}
_modified_files = set()
_phantom_modified = set()  # v4.5: patch "identical"后防find重捕

# SKILL STATS GATE v4.0: 时间冷却替代 FIFO 计数
# 每技能: {skill_name: last_used_timestamp}
_skill_timestamps: Dict[str, float] = {}
_COOLDOWN_SECONDS = 240  # 4分钟

_GATED_L1 = {"terminal", "patch", "write_file", "delegate_task"}
_GATED_L2 = _GATED_L1 | {"read_file", "search_files"}

# v4.3: 源码文件——被 terminal 修改后 read_file 不解锁，需 patch 闭环
_SOURCE_EXTS = (".py", ".md", ".yaml", ".yml", ".json", ".sh", ".toml", ".cfg")

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


def _merge_ranges(ranges):
    """合并重叠/相邻的行范围，返回 [(start, end), ...]。"""
    if not ranges: return []
    sorted_ranges = sorted(ranges)
    merged = [sorted_ranges[0]]
    for s, e in sorted_ranges[1:]:
        ls, le = merged[-1]
        if s <= le + 1:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


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

# v5.0 CSMA/CD Cron Lease Gate
import json as _json

_TRACKER_PATH = os.path.expanduser("~/.hermes/hermes-agent/plugins/housekeeping/tracker.json")
_CRON_JOBS_PATH = os.path.expanduser("~/.hermes/cron/jobs.json")

_cache_lease = {"data": {}, "mtime": 0}
_cache_counter = 0
_CACHE_INTERVAL = 30

def _read_lease():
    try:
        with open(_TRACKER_PATH) as f:
            data = _json.load(f)
        return data.get("housekeeping_lease", {})
    except:
        return {}

def _check_lease():
    global _cache_lease, _cache_counter
    _cache_counter += 1
    if _cache_counter % _CACHE_INTERVAL != 0 and _cache_lease.get("mtime"):
        lease = _cache_lease["data"]
    else:
        try:
            mtime = os.path.getmtime(_TRACKER_PATH)
            if mtime == _cache_lease.get("mtime"):
                lease = _cache_lease["data"]
            else:
                with open(_TRACKER_PATH) as f:
                    data = _json.load(f)
                lease = data.get("housekeeping_lease", {})
                _cache_lease = {"data": lease, "mtime": mtime}
        except:
            lease = {}
    if not lease:
        return None
    expires = lease.get("expires_at", 0)
    started = lease.get("started_at", expires - 15)
    if time.time() < expires:
        elapsed = int(time.time() - started)
        return f"Cron housekeeping in progress (started {elapsed}s ago). Your edit is queued."
    return None

def _cron_healthy():
    try:
        with open(_CRON_JOBS_PATH) as f:
            cron_data = _json.load(f)
        for j in cron_data.get("jobs", []):
            if "\u5bb6\u52a1" in (j.get("name") or ""):
                if j.get("last_status") == "error":
                    return False
                return True
    except:
        pass
    return True


def on_pre_llm_call(**kwargs) -> Optional[Dict[str, str]]:
    global _skills_loaded, _web_searched, _consecutive_skips
    global _needs_doc_sync, _last_modified_doc
    global _loaded_skills_this_turn, _skills_loaded_last_turn, _files_read_this_turn
    global _semantic_audit_pending, _audit_files, _patch_warnings, _audit_verified, _file_snapshots, _modified_files, _phantom_modified

    # 自评估（非关键词——上一轮的 self-rating）

    if not _skills_loaded and not _web_searched:
        _consecutive_skips += 1
    else:
        _consecutive_skips = 0

    # v4.1: 回合边界——上回合的技能进冷却池，本回合清空
    _skills_loaded_last_turn = list(_loaded_skills_this_turn)
    _loaded_skills_this_turn = []
    _files_read_this_turn = {}
    _phantom_modified = set()  # v4.5: 回合重置

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
        remaining = [f for f in _audit_files if not _files_read_this_turn.get(f, {}).get("read_full", False)]
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

    # ── SKILL STATS GATE v4.1: 回合边界冷却 ──
    # 只检查上回合技能——本回合 skill_view 加载的技能永放行
    if tool_name in _GATED_L1 and _skills_loaded_last_turn:
        for skill in _skills_loaded_last_turn:
            ts = _skill_timestamps.get(skill)
            if ts is not None:
                elapsed = time.time() - ts
                if elapsed < _COOLDOWN_SECONDS:
                    temp = int((_COOLDOWN_SECONDS - elapsed) / _COOLDOWN_SECONDS * 100)
                    if temp >= 90:
                        return {
                            "action": "block",
                            "message": (
                                f"🔒 SKILL STATS: {skill} 温度 {temp}°C — 全锁。\\n"
                                f"冷却剩余 {_COOLDOWN_SECONDS - elapsed:.0f}秒。"
                            ),
                        }
                    elif temp >= 70:
                        if tool_name in _GATED_L1:
                            return {"action": "block", "message":
                                f"🔒 SKILL STATS: {skill} 温度 {temp}°C — terminal+patch+write 封锁。\\n"
                                f"冷却剩余 {_COOLDOWN_SECONDS - elapsed:.0f}秒。"}
                    elif temp >= 50:
                        if tool_name == "terminal":
                            return {"action": "block", "message":
                                f"🔒 SKILL STATS: {skill} 温度 {temp}°C — terminal 封锁。\\n"
                                f"冷却剩余 {_COOLDOWN_SECONDS - elapsed:.0f}秒。"}

    # ── 语义审计硬闸 ──
    if _semantic_audit_pending and tool_name in _GATED_L1:
        remaining = [f for f in _audit_files if not _files_read_this_turn.get(f, {}).get("read_full", False)]
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
    # v4.3: patch 不封锁——patch 是审计工具，用来闭环源码修改
    if tool_name in _GATED_L1 and tool_name != "patch" and _modified_files:
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

    # ── v3.8 全读闸门 ──
    # patch/write_file 前必须本回合读过全文件
    if tool_name in ("patch", "write_file"):
        path = args.get("path", args.get("file_path", ""))
        if path:
            norm = os.path.normpath(os.path.expanduser(path))
            entry = _files_read_this_turn.get(norm)
            if not entry:
                if os.path.exists(norm):  # v4.4: 文件存在才拦，新文件放行
                    return {"action": "block", "message":
                        f"🔒 全读闸门: {path} 还没读过。修改前必须 read_file 读全文件。"}
                return None  # 新文件，跳过全读检查
            if not entry.get("read_full", False):
                total = entry.get("total_lines", "?")
                ranges = entry.get("ranges", [])
                lines_read = sum(e - s + 1 for s, e in ranges)
                pct = int(lines_read / total * 100) if total > 0 else 0
                return {"action": "block", "message":
                    f"🔒 全读闸门: {path} 共{total}行，只读了{lines_read}行({pct}%)。读完再改。"}

    # ── v3.8 覆盖率闸门 ──
    # patch 的 old_string 目标行必须在 read 覆盖范围内
    if tool_name == "patch":
        path = args.get("path", args.get("file_path", ""))
        old_str = args.get("old_string", "")
        if path and old_str:
            norm = os.path.normpath(os.path.expanduser(path))
            entry = _files_read_this_turn.get(norm)
            if entry:
                try:
                    with open(norm) as f:
                        file_lines = f.read().split('\n')
                    ol = old_str.split('\n')[0].strip()
                    target = None
                    for i, line in enumerate(file_lines, 1):
                        if ol in line: target = i; break
                    if target:
                        ranges = entry.get("ranges", [])
                        covered = any(s <= target <= e for s, e in ranges)
                        if not covered:
                            rs = ", ".join(f"{s}-{e}" for s, e in ranges)
                            return {"action": "block", "message":
                                f"🔒 覆盖率闸门: 只读了{rs}行，修改目标在第{target}行——超出覆盖范围。"}
                except: pass

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

    # ── v4.2 框架工具闸门: 禁止 terminal curl localhost ──
    if tool_name == "terminal":
        cmd = args.get("command", "")
        if cmd and "curl" in cmd:
            if "localhost:3002" in cmd or "127.0.0.1:3002" in cmd:
                return {"action": "block", "message":
                    "🔒 框架工具闸门: terminal curl localhost:3002 被拦截。\\n"
                    "→ web_search(query=...) 替代搜索（Firecrawl 本地）\\n"
                    "→ web_extract(urls=[...]) 替代抓取（Firecrawl 本地）\\n"
                    "web.backend=firecrawl + FIRECRAWL_API_URL 已配置"}
            if "localhost:8080" in cmd or "127.0.0.1:8080" in cmd:
                return {"action": "block", "message":
                    "🔒 框架工具闸门: terminal curl localhost:8080 被拦截。\\n"
                    "→ browser_navigate(url=\"http://localhost:8080/...\") 替代 SearXNG 搜索"}

    # ── v5.0 维护文件写入闸门 (R3) ──
    if tool_name == "terminal":
        maint_files = ("memo.md", "MAINTENANCE.md", "FAILURES.md", "DONT_DO.md", "MEMORY.md", "SOUL.md")
        redirect_ops = (">>", " > ", "tee ", "cat >", "cat>>", "cp ", " mv ")
        if any(mf.lower() in cmd.lower() for mf in maint_files) and any(op in cmd for op in redirect_ops):
            return {"action": "block", "message":
                "Maintenance file terminal write blocked. Use patch (audited diff) instead."}

    # ── v5.0 Cron Lease Gate (R1+R2) ──
    if tool_name in ("patch", "write_file", "terminal"):
        maint_files = ("memo.md", "MAINTENANCE.md", "FAILURES.md", "DONT_DO.md", "MEMORY.md", "SOUL.md", "jobs.json")
        is_maint = any(mf.lower() in (path or "").lower() for mf in maint_files)
        is_maint_cmd = any(mf.lower() in cmd.lower() for mf in maint_files)
        if is_maint or is_maint_cmd:
            if _cron_healthy():
                block_msg = _check_lease()
                if block_msg:
                    return {"action": "block", "message": f"Cron housekeeping lock active. {block_msg}"}

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
    global _docs_may_be_stale, _needs_doc_sync, _last_modified_doc, _files_read_this_turn
    global _semantic_audit_pending, _audit_files, _patch_warnings, _audit_verified, _modified_files, _file_snapshots, _phantom_modified
    global _skill_timestamps
    args = args if isinstance(args, dict) else {}

    if tool_name == "read_file":
        path = args.get("path", "")
        if path:
            norm = os.path.normpath(os.path.expanduser(path))
            # v3.8: 初始化条目（dict 而非 list）
            if norm not in _files_read_this_turn:
                _files_read_this_turn[norm] = {"ranges": [], "total_lines": 0, "read_full": False}
            entry = _files_read_this_turn[norm]
            offset = args.get("offset", 1)
            limit_val = args.get("limit", 500)
            entry["ranges"].append((offset, offset + limit_val - 1))
            entry["ranges"] = _merge_ranges(entry["ranges"])
            try:
                with open(norm) as f:
                    entry["total_lines"] = len(f.readlines())
            except: pass
            tl = entry["total_lines"]
            # 裁剪到文件实际行数（防止 limit 超大导致 range 超出）
            if tl > 0 and entry["ranges"]:
                entry["ranges"] = [(max(1, s), min(tl, e)) for s, e in entry["ranges"]]
            entry["read_full"] = (entry["ranges"] == [(1, tl)] if tl > 0 else False)
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
            # v4.3: 源码文件不因 read_file 解锁——需 patch 闭环审计
            # 非源码文件（jobs.json, memo.md 等）读就放行
            if norm in _modified_files:
                if any(norm.endswith(ext) for ext in _SOURCE_EXTS):
                    pass  # 源码文件：read 不解锁，等 patch
                else:
                    _modified_files.discard(norm)
            # 语义审计: 全读才算验证通过（v4.5: 10行partial read不算数）
            if _semantic_audit_pending and _audit_files:
                entry = _files_read_this_turn.get(norm)
                if entry and entry.get("read_full", False):
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

            # 语义审计标记
            _semantic_audit_pending = True
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
                if line and line not in _phantom_modified:
                    _modified_files.add(line)
        except: pass

    # v4.3: patch 成功后清除对应文件的 FILE MODIFIED 锁（find之后，防重捕）
    # v4.5: 内容相同时（old==new）无风险，进入幻影集防find重捕
    if tool_name == "patch":
        path = args.get("path", args.get("file_path", ""))
        if path:
            norm = os.path.normpath(os.path.expanduser(path))
            if norm in _modified_files:
                _modified_files.discard(norm)
                _phantom_modified.add(norm)  # v4.5: 内容相同=无风险，不再重捕

    if tool_name in ("skill_view", "skills_list", "skill_manage"):
        _consecutive_skips = 0
        _skills_loaded = True
        skill_name = args.get("name", "")
        if skill_name:
            if skill_name not in _loaded_skills_this_turn:
                _loaded_skills_this_turn.append(skill_name)
            # v3.8: 每次加载都刷新时间戳——不管是不是新技能
            _skill_timestamps[skill_name] = time.time()

    if tool_name in ("web_search", "web_extract", "browser_navigate"):
        _consecutive_skips = 0
        _web_searched = True

    return None


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
