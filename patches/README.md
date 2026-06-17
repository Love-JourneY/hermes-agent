# Hermes 本地补丁管理

## 架构

- `main` 分支 → 跟踪上游，干净
- `local-patches` 分支 → main + 我们的热补丁

详细策略见 `STRATEGY.md`。

## 当前补丁

| 补丁 | 内容 | 涉及文件 | 状态 |
|------|------|----------|------|
| 补丁 | 内容 | 涉及文件 | 状态 |
|------|------|---------|------|
| 001-provider-model-listing-timeout.patch | model listing 超时 3s/5s/8s→15s | `hermes_cli/models.py`、`agent/model_metadata.py` | 本地热补丁 |
| 002-display-hotpatches.patch | web_extract 内容预览 + terminal 首尾行回显 | `agent/display.py` | 本地热补丁 |
| 003-display-execute-code-diff.patch | execute_code 内部 diff 在 TUI 渲染 | `agent/display.py` | 本地热补丁 |
| 004-tools-cron-hotpatches.patch | web_tools 超时 + cron/todo/memory/skill diff 输出 | `tools/*.py`、`cron/jobs.py` | 本地热补丁 |
| background_review.patch | 子代理白名单 + 失败学习 | `agent/background_review.py` | PR #41469 approved, 等合并 |

## 更新流程

```bash
cd ~/.hermes/hermes-agent
git checkout main && git pull origin main    # 1. 拉上游
git checkout local-patches && git rebase main # 2. 重放补丁
```
