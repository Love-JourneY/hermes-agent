# Hermes 本地补丁管理

## 架构

- `main` 分支 → 跟踪上游，干净
- `local-patches` 分支 → main + 我们的热补丁

详细策略见 `STRATEGY.md`。

## 当前补丁

| 补丁 | 内容 | 涉及文件 | 状态 |
|------|------|----------|------|
| 补丁 | 内容 | 涉及文件 | commit |
|------|------|---------|--------|
| 001-provider-model-listing-timeout.patch | model listing 超时 15s | `hermes_cli/models.py` `agent/model_metadata.py` | `4a8dc8e` |
| 002-display-web-extract-hotfix.patch | web_extract 内容预览 hotfix | `agent/display.py` | `22cadee` |
| 003-display-json-diff-refactor.patch | display JSON diff 提取重构 | `agent/display.py` | `24b8038` |
| 004-display-pr1-baseline-sync.patch | display PR1 baseline 同步 | `agent/display.py` | `b766e40` |
| 005-display-terminal-echo.patch | terminal 首尾行回显 | `agent/display.py` | `4b3b2a8` |
| 006-display-web-extract-preview.patch | web_extract 英文片段预览 | `agent/display.py` | `7ab11d3` |
| 007-display-execute-code-diff.patch | execute_code diff 渲染 TUI | `agent/display.py` | `5d5f139` |
| 008-tools-memory-diff.patch | memory 操作 diff 输出 | `tools/memory_tool.py` | `488f1a0` |
| 009-tools-todo-diff.patch | todo 操作 diff 输出 | `tools/todo_tool.py` | `1e01699` |
| 010-tools-firecrawl-timeout.patch | web_tools firecrawl 超时 | `tools/web_tools.py` | `c9efa13` |
| 011-tools-cron-diff.patch | cron job diff 输出 | `tools/cronjob_tools.py` `cron/jobs.py` | `c01a6e0` |
| 012-tools-skill-manage-diff.patch | skill_manage diff 输出 | `tools/skill_manager_tool.py` | `4908882` |
| 013-agent-background-review.patch | background_review read_file 权限 | `agent/background_review.py` | `6834b6a` |

## 更新流程

```bash
cd ~/.hermes/hermes-agent
git checkout main && git pull origin main    # 1. 拉上游
git checkout local-patches && git rebase main # 2. 重放补丁
```
