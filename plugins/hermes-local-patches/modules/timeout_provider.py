"""p001: provider_model_listing_timeout — monkey-patch 超时函数

原热补丁: 001-provider-model-listing-timeout.patch
目标: hermes_cli/models.py + agent/model_metadata.py
改动: 超时 5s/3s → 15s
"""

import logging

NAME = "timeout_provider"
DESCRIPTION = "provider model listing 超时 5s/3s→15s"

_log = logging.getLogger("hermes-local-patches")

_originals = {}
_applied = False


def _patch_module(mod, func_name, new_timeout=15):
    """替换函数的 timeout 默认参数。"""
    if not hasattr(mod, func_name):
        _log.warning("target not found: %s.%s", mod.__name__, func_name)
        return False
    orig = getattr(mod, func_name)
    import functools

    @functools.wraps(orig)
    def wrapped(*args, **kwargs):
        if "timeout" not in kwargs:
            kwargs["timeout"] = new_timeout
        return orig(*args, **kwargs)

    setattr(mod, func_name, wrapped)
    _originals[f"{mod.__name__}.{func_name}"] = orig
    return True


def apply() -> bool:
    global _applied
    if _applied:
        return True

    ok = True

    # 1. hermes_cli.models — probe/fetch timeout
    try:
        import hermes_cli.models as m
        import functools
        for fn in ["probe_api_models", "fetch_api_models"]:
            if hasattr(m, fn):
                orig = getattr(m, fn)
                @functools.wraps(orig)
                def _wrap(*a, _o=orig, **kw):
                    if "timeout" not in kw:
                        kw["timeout"] = 15
                    return _o(*a, **kw)
                setattr(m, fn, _wrap)
                _originals[f"models.{fn}"] = orig
            else:
                _log.warning("models.%s not found", fn)
                ok = False
    except Exception as e:
        _log.warning("models patch failed (non-critical): %s", e)
        # Non-critical — still try agent.model_metadata

    # 2. agent.model_metadata — _query_local_context_length timeout
    try:
        import agent.model_metadata as mm
        import functools
        fn = "_query_local_context_length"
        if hasattr(mm, fn):
            orig = getattr(mm, fn)
            @functools.wraps(orig)
            def _wrap_mm(*a, _o=orig, **kw):
                if "timeout" not in kw:
                    kw["timeout"] = 15
                return _o(*a, **kw)
            setattr(mm, fn, _wrap_mm)
            _originals[f"mm.{fn}"] = orig
        else:
            _log.warning("mm.%s not found", fn)
            ok = False
    except Exception as e:
        _log.warning("mm patch failed: %s", e)
        ok = False

    _applied = ok
    return ok


def revert():
    global _applied
    for key, orig in _originals.items():
        parts = key.rsplit(".", 1)
        if len(parts) == 2:
            mod_name, func_name = parts
            try:
                mod = __import__(mod_name, fromlist=[func_name])
                setattr(mod, func_name, orig)
            except Exception:
                _log.warning("revert failed for %s", key)
    _originals.clear()
    _applied = False


def is_applied() -> bool:
    return _applied
