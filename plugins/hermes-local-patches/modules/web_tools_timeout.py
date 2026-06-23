"""p010: web_tools_firecrawl_timeout — monkey-patch 超时

原热补丁: 010-tools-firecrawl-timeout.patch
目标: tools/web_tools.py
改动: Firecrawl 请求超时配置
"""

import logging
import functools

NAME = "web_tools_timeout"
DESCRIPTION = "Firecrawl 请求超时配置"

_log = logging.getLogger("hermes-local-patches")

_originals = {}
_applied = False


def apply() -> bool:
    global _applied
    if _applied:
        return True

    ok = True

    try:
        import tools.web_tools as wt

        # Patch the Firecrawl query function to increase timeout
        for fname in ["firecrawl_query", "_firecrawl_scrape", "_firecrawl_search"]:
            if hasattr(wt, fname):
                orig = getattr(wt, fname)
                _originals[f"web_tools.{fname}"] = orig

                @functools.wraps(orig)
                def wrapped(*args, _o=orig, **kwargs):
                    if "timeout" not in kwargs or kwargs["timeout"] is None:
                        kwargs["timeout"] = 30
                    return _o(*args, **kwargs)

                setattr(wt, fname, wrapped)
    except ImportError:
        _log.warning("tools.web_tools not available")
        ok = False
    except Exception as e:
        _log.warning("web_tools patch failed: %s", e)
        ok = False

    _applied = ok
    return ok


def revert():
    global _applied
    for key, orig in _originals.items():
        parts = key.split(".", 1)
        if len(parts) == 2:
            mod_name, func_name = parts
            try:
                mod = __import__(f"tools.{mod_name}", fromlist=[func_name])
                setattr(mod, func_name, orig)
            except Exception:
                _log.warning("revert failed for %s", key)
    _originals.clear()
    _applied = False


def is_applied() -> bool:
    return _applied
