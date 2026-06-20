# nija-policy Plugin

Nija's policy enforcement plugin for Hermes Agent. Provides hard-gate security with adaptive fill-in-the-form messages.

## Architecture

All gates run in `on_pre_tool_call` in order:

1. **execute_code gate** — only self-test-protocol can unlock
2. **HARD GATE** — force reflection + skill loading before GATED_L1 tools
3. **Pre-read branch (v5.2)** — compute ranges/read_full BEFORE tool execution; out-of-bounds intercept; dedup-proof
4. **TERMINAL FILE OPS** — block terminal `>` / `sed -i` / `tee`; guide to write_file/patch
5. **SKILL STATS** — per-skill cooldown (time-based, temp ≥50°C blocks)
6. **Content Audit** — verify patch/write_file changes via read_file
7. **SEMANTIC AUDIT** — ✅/❌ verified/unverified files; dedup escape note
8. **渐进闸门** — L2/L3 soft ban on repeated unskilled behavior
9. **P0 doc gate** — write_file blocked on existing .md (must use patch)
10. **execute_code code-mod gate** — block code file writes in execute_code
11. **Full-read gate** — must read full file before patch/write_file
12. **Coverage gate** — old_string target must be in read range
13. **Framework tool gate** — block curl localhost:3002/8080
14. **Memory conflict gate** — grep memory before destructive config changes

## Key Innovations

### Pre-read branch (v5.2, 2026-06-20)
Hermes read_file has built-in dedup: same-turn identical calls bypass execution. This previously caused SEMANTIC AUDIT deadlock because post_tool_call wouldn't fire to update `_files_read_this_turn`.

**Fix**: Compute `total_lines`, update `ranges` and `read_full` in pre_tool_call (BEFORE Hermes decides to dedup). Out-of-bounds requests (limit > total_lines) are blocked with guidance. Large files (>2000 lines) can be read in parts — ranges merge across calls.

### Adaptive Gate Messages (2026-06-20)
All gate block messages changed from "notification" to "fill-in-the-form" format (HARD GATE style).

## Enable/Disable

```bash
hermes plugins enable nija-policy
hermes plugins disable nija-policy
# After change: /exit reconnect
```

## Version History

- v5.1c — SEMANTIC AUDIT round-reset _audit_files; Content Audit Gate
- v5.2 — Pre-read branch for dedup-proof range tracking + out-of-bounds intercept + adaptive gate messages