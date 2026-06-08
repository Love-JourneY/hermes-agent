"""Nija 策略插件——框架级工具拦截。

在 Hermes 原生 pre_tool_call 钩子上挂载。
读 ~/.hermes/config.yaml 的 pre_tool_policy 规则表，
匹配到就拦截。不改 Hermes 源码。

规则格式 (config.yaml):
  pre_tool_policy:
    enabled: true
    rules:
      - tool: terminal
        pattern: "hermes config set"
        message: "⛔ 改配置前先 grep memory + FAILURES.md"
      - tool: patch
        pattern: "*.md"
        message: "⛔ 改文档前 read_file 全篇，改后 diff 验证"
"""
import os
import re
import fnmatch
from typing import Optional, Dict, Any


def _load_rules() -> list:
    """从 config.yaml 加载规则表"""
    import yaml
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
    except Exception:
        return []
    policy = cfg.get("pre_tool_policy", {})
    if not policy.get("enabled"):
        return []
    return policy.get("rules", [])


def _match_rule(tool_name: str, args: dict, rule: dict) -> bool:
    """检查工具调用是否匹配规则"""
    if rule.get("tool") and rule["tool"] != tool_name:
        return False
    pattern = rule.get("pattern", "*")
    if pattern == "*":
        return True
    arg_str = str(args)
    if fnmatch.fnmatch(arg_str, pattern):
        return True
    if re.search(pattern, arg_str):
        return True
    return False


def on_pre_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Optional[Dict[str, str]]:
    """pre_tool_call 钩子——匹配规则 → 拦截"""
    args = args if isinstance(args, dict) else {}
    rules = _load_rules()
    for rule in rules:
        if _match_rule(tool_name, args, rule):
            return {
                "action": "block",
                "message": rule.get("message", f"⛔ 操作被 Nija 策略拦截: {tool_name}"),
            }
    return None
