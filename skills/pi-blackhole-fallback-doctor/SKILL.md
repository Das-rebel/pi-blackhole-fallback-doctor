---
name: pi-blackhole-fallback-doctor
description: Diagnose and fix pi-blackhole observer/reflector/dropper fallback-chain failures — "all candidates exhausted", "observer skipped", dead nested fallbacks, size-skips, provider drift, cooldown persistence. Use when pi-blackhole workers are skipped, cooldown-skipped, silently not running, or the fallback chain never fires.
---

# pi-blackhole Fallback Doctor

Fixes the exact production failure class hit on 2026-11-02/03: observer skipped with
"all candidates failed" despite a fallback chain being "configured".

## The #1 root cause — dead nested fallback keys

pi-blackhole parses per-worker fallback chains **ONLY from top-level config keys**
(`unified-config.ts` ≈ lines 725-730, via `parseModelArray`):

- `observerFallbackModels`
- `reflectorFallbackModels`
- `dropperFallbackModels`

The nested form — `observerModel.fallbacks`, `reflectorModel.fallbacks`,
`dropperModel.fallbacks` — is **never read anywhere in the codebase**. Writing chains
there silently no-ops: candidate list = `[primary]` → primary hits a cooldown →
"all candidates exhausted" → stage skipped. Every historical patch that wrote the
nested key (including "verified" ones) fixed nothing.

```jsonc
// ❌ DEAD CONFIG — parsed by no code path
{ "observerModel": { "provider": "openrouter", "id": "...", "fallbacks": [ ... ] } }

// ✅ CORRECT — the only keys the loader reads
{
  "observerFallbackModels": [
    { "provider": "openrouter", "id": "nvidia/nemotron-3.5-lightning:free" },
    { "provider": "zai", "id": "glm-4.5-flash" },
    { "provider": "ollama-direct", "id": "qwen3:0.6b-8k", "contextWindow": 40000 }
  ]
}
```

Fallback array entries are **objects** (`provider`, `id`, optional `contextWindow`), never
bare strings. `parseModel` preserves `contextWindow` overrides.

## Diagnosis

Run the audit script first — it detects every failure mode below:

```bash
python3 scripts/audit_fallback_chain.py                       # default paths
python3 scripts/audit_fallback_chain.py --config <cfg> --cooldown <cd.json> --strict
```

## The six failure modes

| # | Failure | Signature | Fix |
|---|---------|-----------|-----|
| 1 | Dead nested fallback keys | nested `*.fallbacks` arrays in config; debug shows only primary attempted | Move chain to top-level `*FallbackModels` keys |
| 2 | All candidates cooldown | `cooldown_skip` events then exhaustion; `~/.pi/agent/pi-blackhole/pi-blackhole-cooldown.json` holds expiry seeds | Wait for expiry, or delete seed entries to force retry |
| 3 | Size-skip before attempt | candidate never attempted; `sizeSkippedInCycle`; skip messages consolidation.ts:1384/2333/3011 | Add `contextWindow` override ≥ max chunk (~40000) to entries — esp. local models whose registry window undersizes (qwen3:0.6b-8k registry=8192 vs 40K chunks) |
| 4 | Dead provider / schema drift | 413/422/429 from provider; chain ends in dead models | PONG-verify every chain model (see below); known-bad as of 2026-11-02: `groq/qwen/qwen3.8-27b` (413), `mistral/open-mistral-nemo` (422 store-field drift), `zai-2/*` (coding-plan expired, 429 code 1309) |
| 5 | Local model truncates instructions | `observer.empty {"reason":"tool_not_called"}`; preamble ~24K tok + chunk > ollama `num_ctx` (default 8192) | Rebuild ollama tag with `num_ctx` ≥ preamble+chunk (e.g. 81920) via Modelfile |
| 6 | sessionFallback disabled | session model excluded by design (`sessionFallback: false`) | Chain must terminate in a live fallback (local ollama = reboot-safe terminal) |

## Verification protocol

**Model liveness** — every chain entry must pass with **non-empty text**; exit 0 alone is
insufficient (groq gpt-oss models exit 0 while emitting zero final-text bytes — output
stays in the reasoning channel):

```bash
pi -p --no-session --no-extensions --model <provider>/<id> "reply with exactly PONG"
```

**Structural assert, never substring** — verify edits against the *parsed* structure
(provider-id pairs per worker). A substring check on the serialized dump can pass while
nothing changed (this false-positive happened during the real incident).

**End-to-end force-fallback** (proves traversal to the terminal model):

1. Confirm all remote candidates hold cooldowns (seeds in `pi-blackhole-cooldown.json`)
2. Temporarily set `observeAfterTokens: 100` in `pi-blackhole-config.json` (config
   hot-reloads per event) — stash the original value first
3. Submit a trivial turn in the monitored session; launch gate needs 100% of the token
   threshold since the cursor rebase — 100 trips instantly
4. Watch `~/.pi/agent/pi-blackhole/debug.ndjson` for:
   `cooldown_skip` ×N → `<stage>.agent_start` (terminal model) → `<stage>.result` →
   `cursor.saved` with observer state `"recorded"`
5. **Restore** `observeAfterTokens` from the stash

**Gotchas:** event `ts` stamps can lag filesystem time by ~a day — never date-filter
debug events, filter by content. Refresh cursor/token gauge state before concluding
"observer didn't fire" — an 80% gauge means a miss, not a failure.

## Deeper mechanics

Resolver loop, cooldown file format, size-skip precedence, debug event vocabulary →
[REFERENCE.md](REFERENCE.md).
