#!/usr/bin/env bash
# Re-apply the pi-blackhole local patches to the installed package.
# Idempotent: safe to run repeatedly, and safe to run after an npm update
# (which wipes node_modules/pi-blackhole entirely).
#
# Patches applied:
#   1. runtime.ts        — cooldown/size skips must CONTINUE the candidate
#                          loop instead of terminating it.
#   2. consolidation.ts  — a worker model that runs but never calls its tool
#                          ("tool_not_called") is a CANDIDATE failure: skip it
#                          for this cycle and let the fallback chain take over.
#   3. dist/index.js     — the compiled bundle is what pi actually loads, so
#                          patch 2 must be mirrored into it.
#
# Usage:  bash apply-patches.sh
set -euo pipefail

PKG="${PKG_DIR:-$HOME/.pi/agent/npm/node_modules/pi-blackhole}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$PKG" ]; then
  echo "ERROR: $PKG not found — is pi-blackhole installed?" >&2
  exit 1
fi

# ---------------------------------------------------------------- 1. runtime.ts
if [ -f "$HERE/runtime.ts" ]; then
  cp "$HERE/runtime.ts" "$PKG/src/om/runtime.ts"
  echo "[1/3] runtime.ts restored from durable copy"
else
  echo "[1/3] SKIP runtime.ts (no durable copy at $HERE/runtime.ts)"
fi

# -------------------------------------------------------- 2. consolidation.ts
# Patch the SOURCE so the change survives a rebuild from source.
python3 - "$PKG/src/om/consolidation.ts" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
if "observer.empty_retry" in s:
    print("[2/3] consolidation.ts already patched")
    raise SystemExit(0)
anchor = '''      if (reasonLevel === "warning") {'''
assert s.count(anchor) == 1, f"anchor count = {s.count(anchor)}"
patch = '''      // Local patch: a model that ran but never called the observation tool is
      // a CANDIDATE failure, not a stage outcome. Without this the stage
      // returns "continue" here, the cursor never advances, and the identical
      // chunk fails the same way on every future cycle — the whole observer
      // pass silently produces nothing. Skip this candidate for the cycle and
      // let the fallback chain take the next one (mirrors the turn-cap skip
      // above). A session model with no candidate config has nothing to fall
      // back to, so break out and surface the exhaustion.
      if (reason?.kind === "tool_not_called") {
        runtime.skipFailedForCycle(stageModelForThinking);
        debugLog("observer.empty_retry", {
          coversUpToId,
          model: stageModelForThinking
            ? `${stageModelForThinking.provider}/${stageModelForThinking.id}`
            : undefined,
        });
        if (!stageModelForThinking) break;
        continue;
      }
''' + anchor
open(p, "w", encoding="utf-8").write(s.replace(anchor, patch, 1))
print("[2/3] consolidation.ts patched")
PY

# ------------------------------------------------------------ 3. dist/index.js
# pi loads dist/index.js, so the same change must be mirrored into the bundle.
python3 - "$PKG/dist/index.js" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
if "observer.empty_retry" in s:
    print("[3/3] dist/index.js already patched")
    raise SystemExit(0)
anchor = 'return t.advanceCursor("observer",v,"empty"),S()}return ee==="warning"?'
if s.count(anchor) != 1:
    print(f"[3/3] SKIP dist/index.js — anchor not found (count={s.count(anchor)}); "
          "the bundle layout changed, re-derive the patch", file=sys.stderr)
    raise SystemExit(1)
patch = ('return t.advanceCursor("observer",v,"empty"),S()}'
         'if(Y&&Y.kind==="tool_not_called"){'
         'if(t.skipFailedForCycle(W),F("observer.empty_retry",{coversUpToId:v,'
         'model:W?W.provider+"/"+W.id:void 0}),!W)break;'
         'continue}'
         'return ee==="warning"?')
open(p, "w", encoding="utf-8").write(s.replace(anchor, patch, 1))
print("[3/3] dist/index.js patched")
PY

node --check "$PKG/dist/index.js" && echo "    dist syntax OK"

echo
echo "Verify with:"
echo "  python3 ~/.pi/agent/skills/pi-blackhole-fallback-chain/scripts/verify_fallback_chain.py"
echo "Restart every pi session afterwards — running processes keep the old code in memory."
