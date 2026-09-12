"""Provide solc offline, because solc-bin.ethereum.org is not always reachable.

_Authored by Claude Code_ - 2026-09-12

Both Slither and Mythril want to fetch a solc build at run time: Slither via
solc-select, Mythril via solcx. On a restricted network, or behind an egress
proxy, that fetch hangs and the tool dies with no output.

The official `ethereum/solc` image already contains the exact binary they would
download, so extract it once into .cache/solc/ and hand it to both tools. The
file is named twice because the two tools disagree about naming:

    solc            what `slither --solc` wants
    solc-v0.8.26    what solcx wants to find in SOLCX_BINARY_PATH
"""
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "solc"

SOLC_VERSION = "0.8.26"
SOLC_IMAGE = f"ethereum/solc:{SOLC_VERSION}"
SOLC_PATH_IN_IMAGE = "/usr/bin/solc"


def ensure_solc():
    """Extract solc from the official image into the local cache. Idempotent.

    Returns the cache directory, which contains both naming conventions.
    """
    plain = CACHE / "solc"
    versioned = CACHE / f"solc-v{SOLC_VERSION}"
    if plain.exists() and versioned.exists():
        return CACHE

    CACHE.mkdir(parents=True, exist_ok=True)
    cid = subprocess.check_output(
        ["docker", "create", SOLC_IMAGE], text=True).strip()
    try:
        subprocess.check_call(
            ["docker", "cp", f"{cid}:{SOLC_PATH_IN_IMAGE}", str(plain)],
            stdout=subprocess.DEVNULL)
    finally:
        subprocess.call(["docker", "rm", cid], stdout=subprocess.DEVNULL)

    plain.chmod(0o755)
    shutil.copy2(plain, versioned)
    versioned.chmod(0o755)
    return CACHE
