# pi-blackhole Fallback Mechanics — Reference

Verified against pi-blackhole v0.5.16 (upstream: github.com/k0valik/pi-blackhole),
installed at `~/.pi/agent/npm/node_modules/pi-blackhole/`, config at
`~/.pi/agent/pi-blackhole/pi-blackhole-config.json`.

## Candidate construction (`runtime.ts`, `resolveModel` ≈ lines 745-985)

Per worker stage (observer → reflector → dropper), the candidate list is:

1. The stage's primary model (`<stage>Model` config)
2. The stage's fallbacks — **top-level `<stage>FallbackModels` only** (parsed in
   `unified-config.ts` ≈ 725-730 via `parseModelArray`; `parseModel` preserves
   `contextWindow`)
3. The base `config.model` (session model), only if `sessionFallback` is enabled
   (`false` excludes it — keep it false for deterministic chains)

`MAX_STAGE_ATTEMPTS = 10` — the whole loop **continues on every skip**, so "all
candidates exhausted" with only one `cooldown_skip` logged means the other candidates
never entered the list (dead nested keys / empty top-level arrays).

## Effective context window (size-skip precedence)

A candidate is **skipped without attempt** when effective window < estimated input
tokens (tracked per-cycle in `sizeSkippedInCycle`, checked inside `resolveModel` before
each attempt, cleared per stage/run). Skip messages: `consolidation.ts` lines ≈ 1384,
2333, 3011; output-allowance skip ≈ 1707.

Effective window precedence:
1. Blackhole-config entry `contextWindow` override (`OmModelConfig.contextWindow`)
2. pi model registry value
3. 128K fallback

Consequence: any chain entry lacking an override inherits a possibly-wrong registry
window. Local ollama models frequently undersize (qwen3:0.6b-8k registry=8192 vs 40K+
observer chunks) → permanently size-skipped → recreated "observer skipped" even with a
syntactically perfect chain. **Give every chain entry an explicit `contextWindow`.**

## Cooldown persistence

File: `~/.pi/agent/pi-blackhole/pi-blackhole-cooldown.json` — entries keyed by model,
value = cooldown expiry timestamp. Cooldowns are seeded on failures (429/413/422/5xx)
and honored across restarts. During a long outage, seeds can outlive the outage window;
deleting individual seed entries forces retry. A known-good maintenance move: set seeds
to expire in the near past to re-test a provider.

## Launch gate (observer firing)

The observer fires at turn end when tokens accumulated since the last cursor rebase ≥
`observeAfterTokens` (config hot-reloads per event — no restart needed). A cursor
rebase (e.g. after a successful observation) resets the gauge to 0; a short session
may take several turns to re-trip the gate. For testing, drop `observeAfterTokens`
to 100 (stash the original — restore it after).

## debug.ndjson vocabulary (`~/.pi/agent/pi-blackhole/debug.ndjson`)

Events observed in production: `model.cooldown_skip`, `<stage>.agent_start`,
`<stage>.result`, `<stage>.empty` (with `reason`), `observer.start` (chunk/token
stats), `cursor.saved` (observer state: "recorded" | "empty"), consolidation
skip events.

**Timestamp trap:** the process stamps event `ts` with a date that can lag the
filesystem by ~a day (Nov-02 stamps written on Nov-03). Never filter debug events by
date — filter by content/stage/model.

## num_ctx truncation (local models)

Ollama truncates prompts to `num_ctx` (default 8192) **silently**. Observer chunks ran
41K tokens with a ~24K-token instruction preamble — the tool schema was truncated away,
so the model returned `observer.empty {"reason":"tool_not_called"}` despite coherent
otherwise on-theme output. Fix via Modelfile:

```
FROM qwen3:0.6b-8k
PARAMETER num_ctx 81920
```

then `ollama create qwen3:0.6b-8k -f Modelfile` (overwrites tag), verify with
`ollama show`. Size the window ≥ preamble + max chunk.

## Local terminal fallback (reboot-safe)

- `ollama serve` on 11434 under launchd (`com.ollama.ollama` / `homebrew.mxcl.ollama`,
  PPID 1) survives reboots
- A gateway on 11434+5 is itself a launchd service (`com.ollama.proxy`) — not a manual
  single point of failure
- Provider shape: see pi-blackhole's own `example-config.json` in the installed package
  for `providers` / `providerModels` structure; chain entries reference the provider by
  name plus `id` and optional `contextWindow`

## Verification state at time of writing (2026-11-03)

- Chain traversal verified in production: 4 remote `cooldown_skip`s → dropper
  `agent_start` on local qwen3 → `dropper.result` → `cursor.saved` "recorded"
- Observer infrastructure fixed; quality verification of the rebuilt num_ctx 81920 tag
  (does qwen3 now call the observer tool?) was the next open item
