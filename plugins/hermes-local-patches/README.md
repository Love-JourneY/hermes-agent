# hermes-local-patches — 本地热补丁纯插件化

所有 Hermes 本地 16 个热补丁的纯 monkey-patch 实现。**零磁盘源码修改，100% 运行时注入。**
上游更新 = `git pull upstream main` + `hermes gateway restart` → 自动兼容。

## 架构

```
hermes-local-patches/
├── __init__.py       ← 插件生命周期 + 健康报告
├── plugin.yaml       ← Hermes 元数据
├── loader.py         ← 模块扫描 + apply/revert + 状态追踪
├── modules/          ← 每个 .py 一个补丁模块
│   ├── timeout_provider.py   ← 001: provider 超时 5s→15s
│   ├── display_enhance.py    ← 002-007: display 渲染增强
│   ├── tool_diffs.py         ← 008-012: 工具 diff 输出
│   ├── web_tools_timeout.py  ← 010: Firecrawl 超时
│   ├── exec_code_diff.py     ← injector: execute_code diff 渲染
│   └── background_review.py  ← 013: read_file 权限
└── README.md
```

## 模块标准接口

```python
NAME = "module_name"        # 唯一标识
DESCRIPTION = "..."         # 描述
def apply() -> bool         # 应用 monkey-patch
def revert() -> None        # 恢复原始函数
def is_applied() -> bool    # 当前是否已 patch
```

## 状态查看

```bash
bash ~/.hermes/scripts/plugin-health.sh
# → CHECK hermes-local-patches: ok 🟢 6/6 ok
```

## 逐条测试

### 1. timeout_provider — provider model listing 超时

```python
from venv/bin/python -c "
from hermes_cli.models import probe_api_models
import inspect
# 验证 monkey-patch 后 timeout=15 生效
"
```

### 2. display_enhance — web_extract 预览 / terminal 回显

```python
# 运行 web_extract → 查看结果是否包含 📄 预览标签
# 运行 terminal → 查看是否显示行数和字符数
```

### 3. tool_diffs — 工具 diff 输出

```python
# 运行注意/todo/cron/skill 工具 → 验证结果含 diff 字段
```

### 4. web_tools_timeout — Firecrawl 超时

```python
# 运行 web_search → 验证 timeout 参数被传进 Firecrawl
```

### 5. exec_code_diff — execute_code diff 渲染

```python
# 运行 execute_code 内部调 patch → 验证 TUI 有红绿 diff
```

### 6. background_review — read_file 权限

```python
# 背景 review 子代理应该能调用 read_file
```

## 升级兼容

```bash
git checkout main && git pull upstream main
# 然后重启 — hermes-local-patches 自动适应
# 如果某模块的 target 函数在上游被改名/删除
# → apply() 返回 False → 日志报错 + health degraded
# 手动更新对应模块即可
```

## 与其他插件的关系

- **exec-code-diff-injector**: 功能重叠。local-patches 的 exec_code_diff 模块是替代方案。稳定后 injector 可移除。
- **nija-policy / comprehension-gate**: 独立运行，不受影响。
