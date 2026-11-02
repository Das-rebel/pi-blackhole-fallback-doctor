# Local patches to pi-blackhole (npm)

These patches live in `~/.pi/agent/npm/node_modules/pi-blackhole/src/om/runtime.ts`
and are **wiped by any `npm update` / reinstall of pi-blackhole**. Reapply after updates.

## Patch 1 — skip→continue in resolveModel candidate loop (CRITICAL)
Before: when a chain candidate was on cooldown (or size-skipped), the loop stopped
after the FIRST skip and raised "all candidates exhausted" — the remaining fallbacks
were never attempted, and the terminal local fallback (qwen3) was never reached.

After: a skipped candidate logs `model.cooldown_skip` and CONTINUES to the next
fallback. Verified live 2026-11-02T19:31–19:45 UTC: all 4 remote skips logged,
qwen3 attempted on a 41K chunk, and a real 117K-token backlog cleared as
3 chunks → 31 observations → reflector (45 obs pool).

## Patch 2 — persisted cooldown_skip reason in debug log
`model.cooldown_skip` now emits `until`/`reason`/`cooldownStage` so log-only
readers can compute skip denominators (UI toast was the only carrier before).

## Reapply
```bash
cp patches/runtime.ts ~/.pi/agent/npm/node_modules/pi-blackhole/src/om/runtime.ts
# then restart pi sessions (or wait: config is hot-read per consolidation run,
# but .ts is compiled at import time → restart required)
```

Audit the installed config any time:
```bash
python3 skills/pi-blackhole-fallback-doctor/scripts/audit_fallback_chain.py \
  ~/.pi/agent/pi-blackhole/pi-blackhole-config.json
```
