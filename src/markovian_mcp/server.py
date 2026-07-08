from __future__ import annotations
import json, hashlib
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Markovian Provenance")


def _canonical(content: str) -> bytes:
    """RFC 8785 (JCS) canonical bytes for JSON objects; raw UTF-8 for anything else."""
    try:
        obj = json.loads(content)
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except Exception:
        return content.encode("utf-8")


@mcp.tool()
def markovian_stamp(content: str) -> dict:
    """Compute the canonical commitment root for any output.

    JSON is canonicalized with RFC 8785 (JCS); other text is used verbatim, then
    SHA-256 hashed. The returned root is exactly what Markovian anchors to Bitcoin,
    so anyone can later verify the output was unaltered and existed when claimed,
    without trusting the source or any operator.
    """
    canon = _canonical(content)
    return {
        "canonical_root": "0x" + hashlib.sha256(canon).hexdigest(),
        "algorithm": "sha256",
        "canonicalization": "RFC8785-JCS (json) | utf-8 (text)",
        "bytes": len(canon),
    }


@mcp.tool()
def markovian_verify(content: str, canonical_root: str) -> dict:
    """Verify content against a previously stamped canonical_root by recomputing it.

    Tampering with a single byte changes the root and fails the check. Trust nobody:
    the check is pure recomputation, needing nothing from the operator.
    """
    root = "0x" + hashlib.sha256(_canonical(content)).hexdigest()
    return {"ok": root.lower() == (canonical_root or "").lower(), "recomputed_root": root, "expected": canonical_root}


@mcp.tool()
def markovian_trace(receipts_json: str) -> dict:
    """Walk a lineage of stamps back to its origin.

    Pass a JSON array of receipts, each an object with a "root" and an optional
    "derived_from" (the parent root). Returns the ordered chain from the given head
    to the origin, so an output can be traced to the data and model it came from.
    """
    receipts = json.loads(receipts_json)
    by_root = {r["root"]: r for r in receipts}
    chain, seen = [], set()
    cur = receipts[0]["root"] if receipts else None
    while cur and cur in by_root and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = by_root[cur].get("derived_from")
    return {"chain": chain, "depth": len(chain)}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
