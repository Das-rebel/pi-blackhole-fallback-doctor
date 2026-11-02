# pi-blackhole-fallback-doctor

Diagnose & fix **pi-blackhole** worker fallback-chain failures — the "observer skipped —
all candidates failed" / "all candidates exhausted" class of bug.

## The bug this exists for

pi-blackhole parses per-worker fallback chains **only from top-level config keys**
(`observerFallbackModels` / `reflectorFallbackModels` / `dropperFallbackModels`).
The nested form — `observerModel.fallbacks` — is **never read by any code path**.
Writing chains there silently no-ops: the candidate list is `[primary]` only, the first
cooldown ends the run, and the stage is skipped. Every patch that wrote the nested key
fixed nothing while looking correct.

## Quick audit

```bash
npx pi-blackhole-fallback-doctor        # if published; or:
python3 skills/pi-blackhole-fallback-doctor/scripts/audit_fallback_chain.py
```

Detects: dead nested keys · missing top-level chains · malformed entries · known-bad
provider/model pairs (groq qwen3.8-27b 413, mistral schema-drift 422, zai-2 expired
plan) · missing `contextWindow` overrides (permanent size-skip risk) · currently-active
cooldowns.

## Install as a pi package

Add to `~/.pi/agent/settings.json` → `packages`:

```json
"npm:pi-blackhole-fallback-doctor"
```

or copy the skill into your pi skills dir:

```bash
cp -r skills/pi-blackhole-fallback-doctor ~/.pi/agent/skills/
```

## Covers (all verified in production, 2026-11-02/03)

1. **Dead nested fallback keys** — the root cause; chains must be top-level
2. **All-candidates-cooldown** — persisted seeds in `pi-blackhole-cooldown.json`
3. **Size-skip before attempt** — effective-context-window precedence & the missing
   `contextWindow` override trap (local models undersized vs 40K chunks)
4. **Provider schema drift** — PONG-verify protocol (exit 0 ≠ usable: gpt-oss models
   emit zero final-text bytes)
5. **num_ctx truncation** — ollama silently truncating the 24K-token preamble →
   `observer.empty {"reason":"tool_not_called"}`; rebuild tag with `num_ctx 81920`
6. **sessionFallback disabled** — chain must terminate in a live fallback

Plus the **end-to-end force-fallback verification protocol** (cooldown seeds +
`observeAfterTokens: 100` → watch `debug.ndjson` for full traversal → restore) and
traps (event timestamps lagging a day; gauge-vs-threshold math; structural asserts
instead of substring checks).

See `skills/pi-blackhole-fallback-doctor/SKILL.md` and `REFERENCE.md` for the full
runbook.

## Why a skill?

Each recurrence of this failure cost a full debug session (dead config keys that
"looked" patched, size-skips that bypassed the local fallback, a chain whose terminal
models had drifted dead since being written). This package encodes the entire
diagnosis → fix → verify loop so any agent or human resolves it in minutes.

## License

MIT
