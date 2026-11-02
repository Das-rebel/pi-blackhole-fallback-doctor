#!/usr/bin/env python3
"""Audit a pi-blackhole config for fallback-chain failure modes.

Detects (from the 2026-11-02/03 production incident):
  E1  dead nested fallback keys (<worker>Model.fallbacks — never loaded)
  E2  missing/empty top-level <worker>FallbackModels (single point of failure)
  E3  chain entries not objects / missing provider or id
  E4  known-bad provider/model pairs (schema drift, expired plans, 413)
  W1  entries without explicit contextWindow (size-skip risk; registry
      defaults frequently undersize local models)
  I   resolved chains + currently-cooldown models

  Note: baseUrl is provider-level config (ollama-direct is a built-in provider type);
  chain entries only need provider + id (+ contextWindow override recommended).

Exit codes: 0 = clean/warnings only, 1 = errors (or warnings with --strict).
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

WORKERS = ("observer", "reflector", "dropper")

# Verified-bad as of 2026-11-02 (see skill SKILL.md failure mode 4)
KNOWN_BAD = {
    ("groq", "qwen/qwen3.8-27b"): "413 invalid model",
    ("mistral", "open-mistral-nemo"): "422 extra forbidden store field (Mistral schema drift)",
    ("zai-2", None): "GLM Coding Plan expired — 429 code 1309 on all zai-2 models",
}
BAD_PROVIDER_HINTS = {
    "groq": "groq only serves gpt-oss models, which emit ZERO final-text bytes "
            "(output stays in reasoning channel) — PONG test required",
}


def load(path, what):
    if not os.path.exists(path):
        print(f"  !! {what} not found: {path}")
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"  !! {what} is not valid JSON: {e}")
        return None


def model_str(m):
    if isinstance(m, dict):
        return f"{m.get('provider', '?')}/{m.get('id', '?')}"
    return str(m)


def audit_entry(i, e, errs, warns):
    """Validate one fallback entry. Returns (provider, id) or None."""
    if not isinstance(e, dict):
        errs.append(f"      E3 entry #{i} is not an object (bare strings are "
                    f"never parsed): {e!r}")
        return None
    prov, mid = e.get("provider"), e.get("id")
    if not prov or not mid:
        errs.append(f"      E3 entry #{i} missing provider or id: {e}")
        return None
    key_bad = KNOWN_BAD.get((prov, mid)) or KNOWN_BAD.get((prov, None))
    if key_bad:
        errs.append(f"      E4 {prov}/{mid} is known-bad: {key_bad}")
    if prov in BAD_PROVIDER_HINTS:
        warns.append(f"      W1 {prov}/{mid}: {BAD_PROVIDER_HINTS[prov]}")
    if "contextWindow" not in e:
        warns.append(
            f"      W1 {prov}/{mid} has no contextWindow override — inherits "
            f"registry value (local models often undersized → permanent size-skip)")
    return (prov, mid)


def audit_worker(cfg, worker, errs, warns):
    print(f"\n[{worker}]")
    wmodel = cfg.get(f"{worker}Model")
    if isinstance(wmodel, dict):
        print(f"  primary: {model_str(wmodel)}")
    fb_top = cfg.get(f"{worker}FallbackModels")
    nested = wmodel.get("fallbacks") if isinstance(wmodel, dict) else None

    if nested:
        errs.append(f"  E1 {worker}Model.fallbacks is DEAD CONFIG (never read by "
                    f"unified-config.ts) — {len(nested)} entries silently ignored: "
                    f"{[model_str(m) for m in nested]}")
    if not fb_top:
        errs.append(f"  E2 no top-level {worker}FallbackModels — chain is primary-only; "
                    f"first cooldown ⇒ 'all candidates exhausted' ⇒ stage skipped")
    else:
        print(f"  chain ({len(fb_top)} fallbacks):")
        for i, e in enumerate(fb_top, 1):
            audit_entry(i, e, errs, warns)
            print(f"    #{i} {model_str(e)}")

    sf = cfg.get("sessionFallback")
    if sf is False:
        print("  sessionFallback: false (session model excluded by design — ensure "
              "chain terminates in a live fallback, ideally local ollama)")


def audit_cooldown(path):
    print("\n[cooldowns]")
    cd = load(path, "cooldown file")
    if cd is None:
        return
    now = time.time()
    active = []
    for k, v in (cd.items() if isinstance(cd, dict) else []):
        exp = v.get("expiresAt", v) if isinstance(v, dict) else v
        try:
            exp = float(exp)
            # seconds vs ms heuristic
            if exp > 1e12:
                exp /= 1000.0
        except (TypeError, ValueError):
            continue
        if exp > now:
            when = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%H:%M:%SZ")
            active.append(f"    {k}: until {when} UTC")
    if active:
        print(f"  {len(active)} active cooldown(s) — these models are skipped:")
        for a in active[:12]:
            print(a)
    else:
        print("  no active cooldowns")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    default_cfg = os.path.expanduser(
        "~/.pi/agent/pi-blackhole/pi-blackhole-config.json")
    default_cd = os.path.expanduser(
        "~/.pi/agent/pi-blackhole/pi-blackhole-cooldown.json")
    ap.add_argument("--config", default=default_cfg)
    ap.add_argument("--cooldown", default=default_cd)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on warnings too")
    args = ap.parse_args()

    print(f"config:   {args.config}")
    print(f"cooldown: {args.cooldown}")
    cfg = load(args.config, "config")
    if cfg is None:
        sys.exit(1)

    errs, warns = [], []
    for w in WORKERS:
        audit_worker(cfg, w, errs, warns)
    audit_cooldown(args.cooldown)

    print(f"\n{'=' * 60}")
    if warns:
        print(f"WARNINGS ({len(warns)}):")
        for w in warns:
            print(w)
    if errs:
        print(f"ERRORS ({len(errs)}):")
        for e in errs:
            print(e)
        print("\nVERDICT: BROKEN — fix errors above (see SKILL.md failure modes)")
        return 1
    if warns and args.strict:
        print("VERDICT: BROKEN (--strict) — warnings present")
        return 1
    print(f"VERDICT: {'USABLE with warnings' if warns else 'HEALTHY'} — chains use "
          f"top-level keys, entries are structurally valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
