"""
exec-code-diff-injector v2.1 — 完整数据链路 + manifest 持久化

Plugin-managed source hotpatches — applies patches to upstream files
automatically on enable, restores originals via git on cleanup.
Manifest at ~/.hermes/.exec-diff-manifest.json tracks patch SHA256 + content.

v2.1 adds code_execution_tool.patch (from backup): tool_call_log stores
result["diff"], diff promotion loop raises internal diffs to top-level.
Plus manifest: stale detection, SHA256 verification, patches/-less restore.
"""

import atexit, hashlib, json, os, subprocess, logging
from typing import Optional, Dict, Any

_log = logging.getLogger("exec-diff")
_DIFF_PREFIX = "[EXEC_DIFF]"

# ── Paths ─────────────────────────────────────────────────────────────────
_plugin_dir = os.path.dirname(os.path.abspath(__file__))
_hermes_root = os.path.abspath(os.path.join(_plugin_dir, "..", ".."))
_patches_dir = os.path.join(_plugin_dir, "patches")
_MANIFEST_PATH = os.path.join(os.path.expanduser("~/.hermes"), ".exec-diff-manifest.json")
_PATCH_FILES = [
    "agent_display.patch",
    "acp_adapter_tools.patch",
    "code_execution_tool.patch",
    "tui_gateway_server.patch",
]


# ── Manifest management ───────────────────────────────────────────────────
def _read_manifest() -> Optional[Dict]:
    try:
        with open(_MANIFEST_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def _write_manifest() -> bool:
    patches = {}
    for pf in _PATCH_FILES:
        pp = os.path.join(_patches_dir, pf)
        if not os.path.exists(pp):
            continue
        try:
            with open(pp) as f:
                content = f.read()
            sha256 = hashlib.sha256(content.encode()).hexdigest()
            target = _file_from_patch(pp)
            if target:
                patches[target] = {
                    "sha256": sha256,
                    "diff": content,
                    "source": pf,
                }
        except Exception as e:
            _log.warning("DIAG: manifest build error %s: %s", pf, e)
    manifest = {
        "version": "2.1.0",
        "pid": os.getpid(),
        "applied_at": __import__("datetime").datetime.now().isoformat(),
        "patches": patches,
    }
    try:
        with open(_MANIFEST_PATH, "w") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        _log.warning("DIAG: manifest written %s", _MANIFEST_PATH)
        return True
    except Exception as e:
        _log.warning("DIAG: manifest write failed: %s", e)
        return False


def _clear_manifest() -> bool:
    try:
        if os.path.exists(_MANIFEST_PATH):
            os.remove(_MANIFEST_PATH)
            _git("add", _MANIFEST_PATH)
            _git("commit", "-m", "manifest: cleanup after shutdown", "--allow-empty")
        return True
    except Exception as e:
        _log.warning("DIAG: manifest clear failed: %s", e)
        return False


def _verify_patch(target_file: str) -> bool:
    manifest = _read_manifest()
    if not manifest:
        return False
    info = manifest.get("patches", {}).get(target_file)
    if not info:
        return False
    expected = info["sha256"]
    actual = hashlib.sha256(info["diff"].encode()).hexdigest()
    return actual == expected


# ── Patch management ──────────────────────────────────────────────────────
def _git(*args: str) -> bool:
    try:
        r = subprocess.run(["git"] + list(args), cwd=_hermes_root,
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _apply_patches() -> None:
    """Apply patches to upstream source. Idempotent."""
    for pf in _PATCH_FILES:
        pp = os.path.join(_patches_dir, pf)
        if not os.path.exists(pp):
            _log.warning("DIAG: patch not found: %s", pf)
            continue
        if _git("apply", "--check", pp):
            if _git("apply", pp):
                _log.warning("DIAG: applied %s ✅", pf)
            else:
                _log.warning("DIAG: apply failed: %s", pf)
        elif _git("apply", "--reverse", "--check", pp):
            _log.warning("DIAG: already applied: %s (skip)", pf)
        else:
            _log.warning("DIAG: conflict on: %s", pf)


def _reverse_patches() -> bool:
    """Reverse-apply our patches. patches/ → manifest fallback → checkout."""
    ok = True
    for pf in _PATCH_FILES:
        pp = os.path.join(_patches_dir, pf)
        if os.path.exists(pp):
            if _git("apply", "--reverse", "--check", pp):
                if _git("apply", "--reverse", pp):
                    _log.warning("DIAG: reverse-applied %s ✅", pf)
                else:
                    _log.warning("DIAG: reverse apply failed: %s", pf)
                    ok = False
            else:
                _log.warning("DIAG: conflict on reverse %s — checkout", pf)
                target = _file_from_patch(pp)
                if target and _git("checkout", target):
                    _log.warning("DIAG: fallback checkout %s ✅", target)
                else:
                    ok = False
        else:
            # patches/ deleted — fallback to manifest
            manifest = _read_manifest()
            if not manifest:
                _log.warning("DIAG: patches/ + manifest missing for %s", pf)
                ok = False
                continue
            target = None
            diff_content = None
            for t, info in manifest.get("patches", {}).items():
                if info.get("source") == pf:
                    target, diff_content = t, info.get("diff", "")
                    break
            if not target or not diff_content:
                _log.warning("DIAG: manifest no entry for %s", pf)
                ok = False
                continue
            # Pipe diff to git apply --reverse (stdin)
            try:
                r = subprocess.run(
                    ["git", "apply", "--reverse"],
                    input=diff_content.encode(),
                    cwd=_hermes_root,
                    capture_output=True, timeout=30,
                )
                if r.returncode == 0:
                    _log.warning("DIAG: manifest-reverse %s ✅", pf)
                else:
                    _log.warning("DIAG: manifest-reverse conflict %s — checkout", pf)
                    if not _git("checkout", target):
                        _log.warning("DIAG: manifest-reverse checkout failed %s", target)
                        ok = False
            except Exception as e:
                _log.warning("DIAG: manifest-reverse exception %s: %s", pf, e)
                ok = False
    return ok


def _file_from_patch(patch_path: str) -> Optional[str]:
    """Extract target path from patch header (--- a/...)."""
    try:
        with open(patch_path) as f:
            for line in f:
                if line.startswith("--- a/"):
                    return line[6:].strip()
    except Exception:
        return None
    return None


def restore_originals() -> bool:
    """Restore patched files. Surgical reverse-apply first, checkout fallback."""
    return _reverse_patches()


# ── Diff extraction ───────────────────────────────────────────────────────
def _extract_diff_from_output(output: str) -> Optional[str]:
    if not output: return None
    i = output.find(_DIFF_PREFIX)
    if i >= 0:
        r = output[i + len(_DIFF_PREFIX):].strip()
        return r if r else None
    if "--- a/" in output:
        ls = output.split("\n")
        ds = next((i for i, l in enumerate(ls) if l.startswith("--- a/")), None)
        if ds is not None:
            dl = ls[ds:]
            while dl and not dl[-1].strip(): dl.pop()
            return "\n".join(dl)
    return None


# ── Fallback hooks ────────────────────────────────────────────────────────
_PREAMBLE = """
# [exec-code-diff-injector] monkey-patch hermes_tools.patch for diff capture
import hermes_tools as _ht_di_ht, functools as _ht_di_ft
_ht_di_orig_patch = _ht_di_ht.patch
@_ht_di_ft.wraps(_ht_di_orig_patch)
def _ht_di_wrapped_patch(*_ht_di_a, **_ht_di_kw):
    _ht_di_r = _ht_di_orig_patch(*_ht_di_a, **_ht_di_kw)
    if isinstance(_ht_di_r, dict):
        _ht_di_d = _ht_di_r.get("diff", "")
        if _ht_di_d: print("{_DIFF_PREFIX}"); print(_ht_di_d)
    return _ht_di_r
_ht_di_ht.patch = _ht_di_wrapped_patch
"""


def on_pre_tool_call(
    tool_name: str = "", args: Optional[Dict[str, Any]] = None, **kwargs
) -> Optional[Dict[str, str]]:
    if tool_name != "execute_code": return None
    a = args if isinstance(args, dict) else {}
    c = a.get("code", "")
    if not c: return None
    if not any(kw.lower() in c.lower() for kw in [
        "hermes_tools.patch", "hermes_tools.write_file",
        "from hermes_tools import patch", "from hermes_tools import write_file",
        "from hermes_tools import ", "import hermes_tools",
    ]): return None
    a["code"] = _PREAMBLE + "\n" + c
    return None


def on_post_tool_call(
    tool_name: str = "", args=None, result=None, **kwargs
) -> None:
    if tool_name != "execute_code": return
    r = result if isinstance(result, dict) else {}
    o = r.get("output", "")
    if o and (di := _extract_diff_from_output(str(o))):
        r["diff"] = di


# ── register ──────────────────────────────────────────────────────────────
_display_injected: bool = False


def _shutdown_cleanup() -> None:
    """Auto-revert patches + clear manifest on process exit (atexit)."""
    _log.warning("DIAG: shutdown cleanup — reversing patches + clearing manifest")
    restore_originals()
    _clear_manifest()


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)

    # 0. Detect stale manifest (crash/kill -9 → patches still applied)
    manifest = _read_manifest()
    if manifest and manifest.get("patches"):
        _log.warning("DIAG: stale manifest — cleaning up before re-apply")
        restore_originals()
        _clear_manifest()

    # 1. Apply patches to upstream source
    _apply_patches()

    # 2. Write manifest tracking what we applied
    _write_manifest()

    # 3. Auto-restore on process exit
    atexit.register(_shutdown_cleanup)
    _log.warning("DIAG: atexit cleanup registered (manifest tracked)")

    # 4. Inject _json_diff_tools (runtime fallback)
    global _display_injected
    if not _display_injected:
        try:
            from agent import display
            if "execute_code" not in display._json_diff_tools:
                display._json_diff_tools.add("execute_code")
            _display_injected = True
        except Exception:
            pass
