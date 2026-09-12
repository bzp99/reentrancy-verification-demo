"""Shared schema helpers. Every runner writes the same shape.

_Authored by Claude Code_ - 2026-09-12, from verification-demo-plan.md section 5.

Paths are anchored to the repo root via __file__ rather than the process cwd,
so a runner behaves identically whether invoked from the Makefile, from CI, or
by hand from a subdirectory.
"""
import json
import os
import pathlib
import subprocess
import time

VERDICTS = {"violated", "no_finding", "proved", "unknown", "error"}

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
RAW = ROOT / "out" / "raw"
NORM = ROOT / "out" / "normalized"


def net_args():
    """`DEMO_OFFLINE=1` cuts the containers off the network entirely.

    Use it for the demo-day rehearsal: every tool is supposed to work from the
    local solc cache, and this is the only way to be sure none of them is
    quietly reaching for solc-bin.
    """
    return ["--network", "none"] if os.environ.get("DEMO_OFFLINE") else []


def run(cmd, timeout):
    """Run a command, return (returncode, stdout, stderr, elapsed_ms)."""
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = -1, "", f"process timeout after {timeout}s"
    except FileNotFoundError as e:
        rc, out, err = -1, "", f"command not found: {e}"
    return rc, out, err, int((time.time() - t0) * 1000)


def result(verdict, headline, detail="", trace=None, facts=None, duration_ms=0):
    """One tool's answer about one contract.

    `detail` is prose and should stay to a sentence or two. Anything that is
    code, a location, or a measured value belongs in `facts` as (label, value)
    pairs instead - the renderer sets those in mono and aligns them, which is
    the difference between a readable cell and a wall of run-on tool output.
    `trace` is a witness: mono lines, shown verbatim.
    """
    assert verdict in VERDICTS, verdict
    return {
        "verdict": verdict,
        "headline": headline,
        "detail": detail,
        "trace": trace or [],
        "facts": [list(f) for f in (facts or [])],
        "duration_ms": duration_ms,
    }


def emit(tool_id, name, technique, version, can_prove, results, raw=None):
    NORM.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        (RAW / f"{tool_id}.json").write_text(
            raw if isinstance(raw, str) else json.dumps(raw, indent=2)
        )
    (NORM / f"{tool_id}.json").write_text(json.dumps({
        "id": tool_id, "name": name, "technique": technique,
        "version": version, "can_prove": can_prove, "results": results,
    }, indent=2))
    print(f"[{tool_id}] " + "  ".join(
        f"{k}={v['verdict']}({v['duration_ms']}ms)" for k, v in results.items()))
