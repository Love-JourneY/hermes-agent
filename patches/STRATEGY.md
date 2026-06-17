# 热补丁管理

## 架构

```
main 分支               local-patches 分支
  │                        │
  │ 100% = upstream        ├─ hotfix: provider timeout 3s/5s/8s→15s
  │ (干净跟踪)              │   (3个函数: probe_api_models / fetch_api_models / model_metadata)
  │                        │   (+ ollama cloud discovery 8s→15s)
  │                        ├─ hotfix: read_file whitelist + Reflexion
  │                        │   (上游 PR #41469 approved)
  │                        │
  ▼                        ▼
  git pull upstream main   git rebase main → 补丁重放到新版本
```

## 核心原则

1. **main = upstream** — main 分支永远和上游一模一样，不包含任何本地修改
2. **local-patches = main + 补丁** — 只比 main 多我们的定制 commits
3. **补丁最小化** — 只加框架级强制，不重构上游代码
4. **`git log upstream/main..local-patches`** — 一眼看清所有差异

## 同步流程

```bash
cd ~/.hermes/hermes-agent
git checkout main && git pull upstream main    # 1. 拉上游
git checkout local-patches && git rebase main  # 2. 重放补丁
# 有冲突 → 手动解决 → git rebase --continue
# 无冲突 → 完成
git push origin local-patches                  # 3. 备份到 fork
```

## 永不上游

local-patches 分支在 fork 上备份，但**绝不**提 PR 给 upstream。

## 补丁列表（一个 commit 一个 .patch）

| commit | .patch 文件 | 内容 | 上游状态 |
|--------|------------|------|---------|
| `5d5f139` | 007-display-execute-code-diff.patch | execute_code diff 渲染 TUI | 本地热补丁 |
| `4a8dc8e` | 001-provider-model-listing-timeout.patch | model listing timeout 15s | 本地热补丁 |
| `7ab11d3` | 006-display-web-extract-preview.patch | web_extract 英文片段预览 | 本地热补丁 |
| `4b3b2a8` | 005-display-terminal-echo.patch | terminal 首尾行回显 | 本地热补丁 |
| `22cadee` | 002-display-web-extract-hotfix.patch | web_extract 内容预览 hotfix | 本地热补丁 |
| `24b8038` | 003-display-json-diff-refactor.patch | JSON diff 提取重构 | 本地热补丁 |
| `b766e40` | 004-display-pr1-baseline-sync.patch | display PR1 baseline 同步 | 本地热补丁 |
| `488f1a0` | 008-tools-memory-diff.patch | memory diff 输出 | 本地热补丁 |
| `1e01699` | 009-tools-todo-diff.patch | todo diff 输出 | 本地热补丁 |
| `c9efa13` | 010-tools-firecrawl-timeout.patch | web_tools 超时 | 本地热补丁 |
| `c01a6e0` | 011-tools-cron-diff.patch | cron job diff 输出 | 本地热补丁 |
| `4908882` | 012-tools-skill-manage-diff.patch | skill_manage diff 输出 | 本地热补丁 |
| `6834b6a` | 013-agent-background-review.patch | background_review read_file 权限 | PR #41469 approved |
| 待定（多commit） | feat(tools): cron/memory/todo/skill diff 输出 | 本地热补丁 |
| 待定（#41469） | fix(agent): background_review read_file 白名单 | PR #41469 approved |
