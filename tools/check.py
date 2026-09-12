#!/usr/bin/env python3
"""Fail the build when the analyses stop saying what they must say.

_Authored by Claude Code_ - 2026-09-12.

The rest of the pipeline is deliberately failure-tolerant: every runner
swallows its own errors so that one broken tool cannot take the page down.
That is right for publishing and useless as a gate - a pull request that
reintroduces the bug would still go green.

This is the gate. It asserts the two claims the project actually makes:

  SafeVault must stay provably safe.   If a change moves the state writes back
  below the external call, the proof disappears and this fails. That is the
  check that would have stopped the change.

  VulnerableVault must stay caught.    A canary. If the specimen stops being
  flagged, the analysis has rotted - a tool version bump, a lost solc, a
  silently empty result - and the page would be quietly lying.

Scanners are held to a looser standard than the prover: they may error or time
out (Mythril regularly needs five minutes per contract) without failing the
build, but they may never report the fixed contract as violated.
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (case, tool) -> the verdict that must be present. These are the load-bearing
# claims; anything else here is a failure, including `error`.
REQUIRE = {
    ("safe", "smtchecker"): ({"proved"},
                             "the fixed contract must remain provably safe"),
    ("vulnerable", "smtchecker"): ({"violated"},
                                   "the specimen must still be caught"),
}

# (case, tool) -> verdicts that must NOT appear. Tolerant of error/timeout.
FORBID = {
    ("safe", "slither"): ({"violated"},
                          "the fixed contract must not trip a reentrancy detector"),
    ("safe", "mythril"): ({"violated"},
                          "the fixed contract must not trip a reentrancy detector"),
    ("vulnerable", "slither"): (set(), ""),
}


def verdict(doc, case, tool_id):
    for t in doc["tools"]:
        if t["id"] == tool_id:
            return t["results"].get(case, {}).get("verdict", "missing")
    return "missing"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(ROOT / "out/results.json"))
    a = ap.parse_args()

    src = pathlib.Path(a.input)
    if not src.exists():
        print(f"FAIL  no results at {src}")
        return 1
    doc = json.loads(src.read_text())

    failures = []

    for (case, tool), (allowed, why) in REQUIRE.items():
        got = verdict(doc, case, tool)
        ok = got in allowed
        print(f"{'ok  ' if ok else 'FAIL'}  {tool:<11} {case:<11} "
              f"= {got:<11} (expected {'/'.join(sorted(allowed))})")
        if not ok:
            failures.append(f"{tool} on {case}: expected "
                            f"{'/'.join(sorted(allowed))}, got {got} - {why}")

    for (case, tool), (banned, why) in FORBID.items():
        if not banned:
            continue
        got = verdict(doc, case, tool)
        ok = got not in banned
        print(f"{'ok  ' if ok else 'FAIL'}  {tool:<11} {case:<11} "
              f"= {got:<11} (must not be {'/'.join(sorted(banned))})")
        if not ok:
            failures.append(f"{tool} on {case}: {got} is not allowed - {why}")

    print()
    if failures:
        print("GATE FAILED")
        for f in failures:
            print(f"  - {f}")
        print("\nIf this ran on a pull request, the change under review broke "
              "a property that was previously proved to hold.")
        return 1

    print("GATE PASSED  - the fix is still provable, the specimen is still caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
