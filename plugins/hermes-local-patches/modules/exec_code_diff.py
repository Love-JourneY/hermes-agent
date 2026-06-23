"""exec_code_diff — monkey-patch execute_code diff 渲染
P1-P6: handle_function_call TLS + counter-based result injection + diff promotion
"""
import logging, functools, json, threading
NAME = "exec_code_diff"
DESCRIPTION = "execute_code 内部 diff 渲染到 TUI"
_log = logging.getLogger("hermes-local-patches")
_originals = {}; _applied = False
_tool_call_counter = 0; _call_results = {}; _call_lock = threading.Lock(); _ACTIVE_CALL_LOG = []
_HFC_PATCHED = False; _orig_hfc = None

def _ensure_hfc():
    """Lazy-patch handle_function_call when model_tools is ready."""
    global _HFC_PATCHED, _orig_hfc
    if _HFC_PATCHED: return True
    try:
        import model_tools as m
        o = getattr(m, "handle_function_call", None)
        if o is None: return False
        _orig_hfc = o; _originals["hfc"] = o
        @functools.wraps(o)
        def _patched_hfc(tn, ta, tid=None):
            global _tool_call_counter, _call_results
            r = _orig_hfc(tn, ta, task_id=tid)
            with _call_lock: _tool_call_counter += 1; _call_results[_tool_call_counter] = r
            return r
        m.handle_function_call = _patched_hfc
        _HFC_PATCHED = True; _log.debug("P3 applied lazily"); return True
    except Exception as e:
        _log.warning("P3 lazy: %s", e); return False

def apply():
    global _applied
    if _applied: return True
    ok = True
    try:
        import agent.display as d
        if hasattr(d, "_json_diff_tools"):
            if "execute_code" not in d._json_diff_tools: d._json_diff_tools.add("execute_code")
            _originals["disp"] = True
    except: ok = False
    try:
        import acp_adapter.tools as a
        if hasattr(a, "_format_execute_code_result"):
            o = a._format_execute_code_result; _originals["acp"]=o
            @functools.wraps(o)
            def f(r):
                d = json.loads(r) if r else {}
                p = [f"Exit code: {d.get('exit_code')}" if d.get('exit_code') is not None else "Execution complete"]
                if d.get("diff"): p.extend(["","Diff:",d["diff"]])
                if d.get("output"): p.extend(["","Output:",d["output"]])
                if d.get("error"): p.extend(["","Error:",d["error"]])
                return "\n".join(p)
            a._format_execute_code_result = f
    except: pass
    # P3: lazy — defer to _ensure_hfc()
    try:
        import model_tools as m
        if not _ensure_hfc(): _log.warning("P3 deferred (model_tools not ready)")
    except Exception as e: _log.warning("P3 init: %s", e)
    try:
        import tools.code_execution_tool as c
        if hasattr(c,"_rpc_server_loop"):
            o=c._rpc_server_loop; _originals["rsl"]=o
            @functools.wraps(o)
            def p4(srv,tid,cl,cc,mx,al):
                _ensure_hfc()
                global _ACTIVE_CALL_LOG; _ACTIVE_CALL_LOG=cl; bl,bc=len(cl),_tool_call_counter
                try: return o(srv,tid,cl,cc,mx,al)
                finally:
                    for i in range(len(cl)-bl):
                        idx,ct=bl+i,bc+1+i
                        r=_call_results.get(ct)
                        if r is not None and idx<len(cl) and isinstance(cl[idx],dict) and "result" not in cl[idx]: cl[idx]["result"]=r
            c._rpc_server_loop=p4
        else: ok=False
    except Exception as e: _log.warning("P4 %s",e); ok=False
    try:
        import tools.code_execution_tool as c
        if hasattr(c,"_rpc_poll_loop"):
            o=c._rpc_poll_loop; _originals["rpl"]=o
            @functools.wraps(o)
            def p5(env,rd,tid,cl,cc,mx,al,se):
                _ensure_hfc()
                global _ACTIVE_CALL_LOG; _ACTIVE_CALL_LOG=cl; bl,bc=len(cl),_tool_call_counter
                try: return o(env,rd,tid,cl,cc,mx,al,se)
                finally:
                    for i in range(len(cl)-bl):
                        idx,ct=bl+i,bc+1+i
                        r=_call_results.get(ct)
                        if r is not None and idx<len(cl) and isinstance(cl[idx],dict) and "result" not in cl[idx]: cl[idx]["result"]=r
            c._rpc_poll_loop=p5
    except Exception as e: _log.warning("P5 %s",e)
    try:
        import tools.code_execution_tool as c
        if hasattr(c,"execute_code"):
            o=c.execute_code; _originals["ec"]=o
            @functools.wraps(o)
            def p6(code,task_id=None,enabled_tools=None):
                global _ACTIVE_CALL_LOG,_tool_call_counter,_call_results
                _ACTIVE_CALL_LOG=[];_tool_call_counter=0;_call_results={}
                rj=o(code,task_id=task_id,enabled_tools=enabled_tools)
                if _ACTIVE_CALL_LOG:
                    try:
                        r=json.loads(rj) if isinstance(rj,str) else rj
                        if isinstance(r,dict):
                            diffs=[]
                            for e in _ACTIVE_CALL_LOG:
                                raw=e.get("result","{}")
                                try:
                                    cr=json.loads(raw) if isinstance(raw,str) else (raw or {})
                                    if cr.get("diff"): diffs.append(cr["diff"])
                                except: pass
                            if diffs: r["diff"]="\n".join(diffs); rj=json.dumps(r)
                    except: pass
                return rj
            c.execute_code=p6
        else: ok=False
    except Exception as e: _log.warning("P6 %s",e); ok=False
    _applied=ok; return ok

def revert():
    global _applied
    import tools.code_execution_tool as c, model_tools as m, acp_adapter.tools as a
    if "ec" in _originals: c.execute_code=_originals["ec"]
    if "rpl" in _originals: c._rpc_poll_loop=_originals["rpl"]
    if "rsl" in _originals: c._rpc_server_loop=_originals["rsl"]
    if "hfc" in _originals and _HFC_PATCHED: m.handle_function_call=_originals["hfc"]
    if "acp" in _originals: a._format_execute_code_result=_originals["acp"]
    if "disp" in _originals:
        import agent.display as d
        if hasattr(d,"_json_diff_tools"): d._json_diff_tools.discard("execute_code")
    _originals.clear(); _applied=False

def is_applied(): return _applied
