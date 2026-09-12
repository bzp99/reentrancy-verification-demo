#!/usr/bin/env python3
"""SMTChecker runner - CHC model checking via solc's built-in engine.

_Authored by Claude Code_ - 2026-09-12.

This is the only runner that may emit `proved`. It drives solc through
--standard-json so the model checker is scoped to exactly one contract and the
diagnostics come back as structured `errors` entries rather than scraped text.

The Horn solver is Eldarica, not z3. No official solc binary ships a Horn solver: 0.7.6, 0.8.26 and
0.8.36 all answer "Solver z3 was selected for SMTChecker but it is not
available", and the WASM build that does bundle z3 dies with "thread
constructor failed". solc accepts exactly two Horn solvers, and Eldarica
publishes a statically linked native binary - so docker/smtchecker pairs that
with the stock compiler. See that Dockerfile.
"""
import json
import pathlib
import subprocess
import time

from schema import CONTRACTS, ROOT, net_args, run, result, emit

IMAGE = "vdemo/smtchecker:0.8.26"
DOCKERFILE_DIR = ROOT / "docker" / "smtchecker"
SOLVER = "eld"
SOLVER_NAME = "Eldarica"
CHECKER_TIMEOUT_MS = 60000

CASES = {"vulnerable": ("VulnerableVault.sol", "VulnerableVault"),
         "safe":       ("SafeVault.sol", "SafeVault")}

# Captured from the real output of solc 0.8.26 + Eldarica 2.3. The
# parser also matches on message text so a version bump that renumbers these
# will not silently break the demo.
CODE_VIOLATION = 6328   # "CHC: Assertion violation happens here."
CODE_PROVED = 9576      # "CHC: Assertion violation check is safe!"


def ensure_image():
    """Build the solc+Eldarica image if it is not present. Idempotent."""
    rc, _, _, _ = run(["docker", "image", "inspect", IMAGE], 60)
    if rc == 0:
        return
    print(f"[smtchecker] building {IMAGE} ...")
    subprocess.check_call(["docker", "build", "-t", IMAGE, str(DOCKERFILE_DIR)])


def standard_json(filename, contract):
    src = (CONTRACTS / filename).read_text()
    return json.dumps({
        "language": "Solidity",
        "sources": {filename: {"content": src}},
        "settings": {
            "modelChecker": {
                "engine": "chc",
                "targets": ["assert"],
                "solvers": [SOLVER],
                "timeout": CHECKER_TIMEOUT_MS,
                "contracts": {filename: [contract]},
                "showProvedSafe": True,
            },
            "outputSelection": {"*": {"*": []}},
        },
    })


def site_of(msg):
    """Pull `File.sol:27:9` out of solc's formatted diagnostic."""
    for ln in msg.splitlines():
        s = ln.strip()
        if s.startswith("-->"):
            return s[3:].strip().rstrip(":")
    return "—"


def source_excerpt(msg):
    """Pull the quoted source location out of a formatted CHC diagnostic."""
    lines = []
    for ln in msg.splitlines():
        s = ln.strip()
        if s.startswith("-->") or (s and s[0].isdigit() and "|" in s):
            lines.append(s)
    return lines[:6]


def classify(errors, ms):
    violations = [e for e in errors
                  if e.get("errorCode") == CODE_VIOLATION
                  or "assertion violation happens" in e.get("message", "").lower()]
    if violations:
        e = violations[0]
        msg = e.get("formattedMessage") or e.get("message", "")
        return result("violated",
                      "CHC: assertion violation reachable",
                      "A reachable state exists in which the solvency "
                      "assertion does not hold.",
                      # No `site` fact here: the trace below already quotes
                      # the offending line with its location.
                      facts=[
                          ["engine", "CHC (Constrained Horn Clauses)"],
                          ["solver", SOLVER_NAME],
                      ],
                      trace=source_excerpt(msg), duration_ms=ms)

    proved = [e for e in errors
              if e.get("errorCode") == CODE_PROVED
              or "check is safe" in e.get("message", "").lower()
              or "proved safe" in e.get("message", "").lower()]
    if proved:
        e = proved[0]
        msg = e.get("formattedMessage") or e.get("message", "")
        return result("proved",
                      "CHC: assertion violation check is safe",
                      "Not an absence of findings – a proof. It covers "
                      "re-entrant callbacks from code that does not exist yet.",
                      facts=[
                          ["engine", "CHC (Constrained Horn Clauses)"],
                          ["solver", SOLVER_NAME],
                          ["site", site_of(msg)],
                      ],
                      duration_ms=ms)

    fatal = [e for e in errors if e.get("severity") == "error"]
    if fatal:
        return result("error", "Compilation failed",
                      " ".join(fatal[0].get("message", "").split())[:600],
                      duration_ms=ms)

    return result("unknown",
                  "CHC could not decide within the timeout",
                  "No counterexample and no proof. Raise the model-checker "
                  "timeout or simplify the property.", duration_ms=ms)


def analyze(filename, contract):
    cmd = ["docker", "run", "--rm", "-i", *net_args(), IMAGE, "--standard-json"]
    inp = standard_json(filename, contract)
    t0 = time.time()
    try:
        p = subprocess.run(cmd, input=inp, capture_output=True,
                           text=True, timeout=600)
        stdout, stderr = p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        ms = int((time.time() - t0) * 1000)
        return result("error", "solc timed out at the process level",
                      "No response within 600s.", duration_ms=ms), ""
    ms = int((time.time() - t0) * 1000)
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return result("error", "solc produced no parseable output",
                      stderr[-600:], duration_ms=ms), stdout
    return classify(data.get("errors", []), ms), stdout


def main():
    ensure_image()
    _, ver, _, _ = run(["docker", "run", "--rm", IMAGE, "--version"], 120)
    version = next((l.split()[-1] for l in ver.splitlines() if "Version" in l),
                   IMAGE.split(":")[-1])
    _, eld_ver, _, _ = run(["docker", "run", "--rm", "--entrypoint", "eld",
                            IMAGE, "-h"], 120)
    eld = next((l.strip() for l in eld_ver.splitlines() if "Eldarica" in l),
               "Eldarica")

    raws, results = {}, {}
    for case, (fn, contract) in CASES.items():
        results[case], raws[case] = analyze(fn, contract)
    emit("smtchecker", "SMTChecker",
         f"Constrained Horn Clause model checking – {eld}",
         version, can_prove=True,
         results=results, raw=json.dumps(raws, indent=2))


if __name__ == "__main__":
    main()
