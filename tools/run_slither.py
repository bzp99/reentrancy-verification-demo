#!/usr/bin/env python3
"""Slither runner - static analysis over SlithIR.

_Authored by Claude Code_ - 2026-09-12, from verification-demo-plan.md section 5.

Slither cannot prove anything: it either fires a detector or it does not.
A clean run therefore emits `no_finding`, never `proved`.

The runner passes an explicit --solc binary. Without it solc-select tries to
download solc 0.8.26 and, on a network that cannot reach solc-bin.ethereum.org,
Slither exits 1 with no stdout and no stderr at all.
"""
import json

from schema import CONTRACTS, net_args, run, result, emit
from solc_cache import ensure_solc

IMAGE = "trailofbits/eth-security-toolbox:nightly"
CASES = {"vulnerable": "VulnerableVault.sol", "safe": "SafeVault.sol"}

# Slither's own split: `reentrancy-eth` is a write-after-call that can move
# ether, `reentrancy-benign`/`-events` are weaker patterns. Only the first is
# the bug this demo is about.
SEVERE = "reentrancy-eth"


def analyze(filename, solc_dir):
    cmd = ["docker", "run", "--rm", *net_args(),
           "-v", f"{CONTRACTS}:/src:ro",
           "-v", f"{solc_dir / 'solc'}:/opt/solc:ro",
           "--entrypoint", "slither", IMAGE,
           f"/src/{filename}", "--solc", "/opt/solc", "--json", "-"]
    rc, out, err, ms = run(cmd, timeout=300)

    # Slither exits nonzero when it finds something. That is not an error.
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return result("error", "Slither produced no parseable output",
                      (err or "no output")[-600:], duration_ms=ms), out

    dets = data.get("results", {}).get("detectors", [])
    severe = [d for d in dets if d.get("check") == SEVERE]
    if severe:
        d = severe[0]
        return result(
            "violated",
            f"{d['check']} - {d.get('impact', '?')} impact, "
            f"{d.get('confidence', '?')} confidence",
            " ".join(d.get("description", "").split())[:900],
            duration_ms=ms,
        ), out

    others = [d.get("check") for d in dets]
    return result("no_finding",
                  "No reentrancy detector fired",
                  f"{len(dets)} finding(s) of other kinds: "
                  f"{', '.join(others) if others else 'none'}.",
                  duration_ms=ms), out


def main():
    solc_dir = ensure_solc()
    _, ver, _, _ = run(["docker", "run", "--rm", "--entrypoint", "slither",
                        IMAGE, "--version"], 120)
    raws, results = {}, {}
    for case, fn in CASES.items():
        results[case], raws[case] = analyze(fn, solc_dir)
    emit("slither", "Slither",
         "Static analysis - dataflow over SlithIR",
         ver.strip() or "unknown", can_prove=False,
         results=results, raw=json.dumps(raws, indent=2))


if __name__ == "__main__":
    main()
