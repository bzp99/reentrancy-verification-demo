#!/usr/bin/env python3
"""Slither runner - static analysis over SlithIR.

_Authored by Claude Code_ - 2026-09-12.

Slither cannot prove anything: it either fires a detector or it does not.
A clean run therefore emits `no_finding`, never `proved`.

The runner passes an explicit --solc binary. Without it solc-select tries to
download solc 0.8.26 and, on a network that cannot reach solc-bin.ethereum.org,
Slither exits 1 with no stdout and no stderr at all.
"""
import json
import re

from schema import CONTRACTS, net_args, run, result, emit
from solc_cache import ensure_solc

IMAGE = "trailofbits/eth-security-toolbox:nightly"
CASES = {"vulnerable": "VulnerableVault.sol", "safe": "SafeVault.sol"}

# Slither's own split: `reentrancy-eth` is a write-after-call that can move
# ether, `reentrancy-benign`/`-events` are weaker patterns. Only the first is
# the bug this demo is about.
SEVERE = "reentrancy-eth"

# Slither reports paths relative to its own working directory inside the
# container, so every reference reads "../../src/VulnerableVault.sol#23".
# The prefix is noise on a page that shows the file right below the table.
PATH_NOISE = re.compile(r"\.{0,2}[./]*src/")

# Which element of a detector hit goes under which label on the page.
ROLE = {"external_calls": "external call",
        "variables_written": "written after"}


def clean(text):
    return PATH_NOISE.sub("", " ".join(text.split()))


def lineref(lines):
    """[14,15,...,28] -> 'L14–28'; [20] -> 'L20'."""
    if not lines:
        return ""
    lo, hi = min(lines), max(lines)
    return f"L{lo}" if lo == hi else f"L{lo}–{hi}"


def facts_from(detector):
    """Turn Slither's structured elements into labelled, mono-set facts.

    Far better than slicing the prose `description`, which is a multi-line
    report that reads as one run-on paragraph once whitespace is collapsed.
    """
    facts = []
    for e in detector.get("elements", []):
        lines = e.get("source_mapping", {}).get("lines", [])
        name = clean(e.get("name", ""))
        if e.get("type") == "function":
            facts.append(["function", f"{name}()  {lineref(lines)}"])
            continue
        role = ROLE.get(e.get("additional_fields", {}).get("underlying_type"))
        if role:
            facts.append([role, f"{name}  {lineref(lines)}"])
    return facts


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
            f"{d['check']} – {d.get('impact', '?')} impact, "
            f"{d.get('confidence', '?')} confidence",
            "Guarding state is written after control passes to an address "
            "the caller chooses.",
            facts=facts_from(d),
            duration_ms=ms,
        ), out

    others = sorted({d.get("check") for d in dets})
    return result("no_finding",
                  "No reentrancy detector fired",
                  "Every state write happens before the external call.",
                  facts=[["other findings",
                          ", ".join(others) if others else "none"]],
                  duration_ms=ms), out


def main():
    solc_dir = ensure_solc()
    _, ver, _, _ = run(["docker", "run", "--rm", "--entrypoint", "slither",
                        IMAGE, "--version"], 120)
    raws, results = {}, {}
    for case, fn in CASES.items():
        results[case], raws[case] = analyze(fn, solc_dir)
    emit("slither", "Slither",
         "Static analysis – dataflow over SlithIR",
         ver.strip() or "unknown", can_prove=False,
         results=results, raw=json.dumps(raws, indent=2))


if __name__ == "__main__":
    main()
