#!/usr/bin/env python3
"""markovian-mcp - the Markovian provenance stamp, as MCP tools (stdio).

This package is the stdio door to the SAME server the protocol runs at
https://api.markovianprotocol.com/mcp/ . The tool names, parameters and returned
objects are identical, so an agent written against one works unchanged against
the other. Local stdio or hosted HTTP is a choice of transport, not of semantics.

Tools:
  markovian_stamp(data, wallet?, label?, derived_from?)
      Commit `data` to the Markovian chain and return the canonical
      markovian-provenance/v1 object, mirrored under the result's `_meta` key
      "com.markovianprotocol/provenance".
  markovian_verify(merkle_root)
      Independent lookup against the public verifier.
  markovian_trace(merkle_root)
      Walk a stamp's derived_from lineage and report what actually checks out.

Trust model: a stamp proves data was COMMITTED at a time, NOT that it is correct.
PROVENANCE, NOT TRUTH. Verification is a public GET against the verifier, so a
party who distrusts the stamper can run it themselves; nothing here asks anyone
to take this server's word for anything.
"""
from __future__ import annotations

import hashlib
import json

import anyio
import httpx
import mcp.types as types
from mcp.server.lowlevel import Server

API_BASE = "https://api.markovianprotocol.com"
SCHEMA = "markovian-provenance/v1"
ATTESTATION = (
    "provenance-only; proves data was committed at this time, not that it is correct"
)
PROV_KEY = "com.markovianprotocol/provenance"  # reverse-DNS; not a reserved prefix
TIMEOUT = 30.0
VERSION = "0.2.0"

server = Server("markovian", version=VERSION)


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _lineage_refs(derived_from):
    refs = []
    for d in derived_from or []:
        mr, dh = d.get("merkle_root"), d.get("data_hash")
        if not mr or not dh:
            raise ValueError("each derived_from item needs merkle_root and data_hash")
        refs.append({
            "merkle_root": mr,
            "data_hash": dh,
            "schema": d.get("schema", SCHEMA),
            "relationship": d.get("relationship", "derivedFrom"),
        })
    refs.sort(key=lambda r: r["merkle_root"])
    return refs


def publish_payload(root, payload):
    r = httpx.post(f"{API_BASE}/trace/publish",
                   json={"root": root, "payload": payload}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def stamp_output(data: str, wallet=None, label=None, derived_from=None) -> dict:
    """POST /stamp and assemble the canonical markovian-provenance/v1 object.

    With derived_from, the lineage is bound INSIDE the committed bytes (the links
    live in the pre-image of data_hash), so an edge cannot be added or removed
    afterwards without changing the root. The payload is then published so
    markovian_trace can walk to it.
    """
    if derived_from is None:
        resp = httpx.post(
            f"{API_BASE}/stamp",
            json={"data": data, "label": label, **({"wallet": wallet} if wallet else {})},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        s = resp.json()
        root = s["merkle_root"]
        return {
            "schema": SCHEMA, "merkle_root": root, "data_hash": s["data_hash"],
            "wallet": s.get("wallet") or wallet, "zk_commitment": s.get("zk_commitment"),
            "block_height": s.get("block_height"), "stamped_at": str(s.get("stamped_at")),
            "verify": s.get("verify_url") or f"{API_BASE}/verify/{root}",
            "attestation": ATTESTATION,
        }

    refs = _lineage_refs(derived_from)
    payload = {"schema": SCHEMA, "derived_from": refs,
               "body_hash": hashlib.sha256(_canon(data)).hexdigest(),
               "produced_by": "mcp"}
    data_hash = hashlib.sha256(_canon(payload)).hexdigest()
    resp = httpx.post(
        f"{API_BASE}/stamp",
        json={"data_hash": data_hash, "label": label, **({"wallet": wallet} if wallet else {})},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    s = resp.json()
    root = s["merkle_root"]
    try:
        publish_payload(root, payload)
    except Exception:  # noqa: BLE001 - an unpublished payload is an unresolved
        pass           # frontier for trace, not a failed stamp.
    return {
        "schema": SCHEMA, "merkle_root": root, "data_hash": s["data_hash"],
        "wallet": s.get("wallet") or wallet, "zk_commitment": s.get("zk_commitment"),
        "block_height": s.get("block_height"), "stamped_at": str(s.get("stamped_at")),
        "verify": s.get("verify_url") or f"{API_BASE}/verify/{root}",
        "attestation": ATTESTATION, "derived_from": refs,
    }


def verify_root(merkle_root: str) -> dict:
    """Independent existence + commitment lookup against the public verifier."""
    try:
        r = httpx.get(f"{API_BASE}/verify/{merkle_root}", timeout=TIMEOUT)
    except Exception as e:  # noqa: BLE001
        return {"verified": False, "error": str(e), "merkle_root": merkle_root}
    if r.status_code != 200:
        return {"verified": False, "status": r.status_code, "merkle_root": merkle_root}
    try:
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {"verified": False, "error": f"non-json verifier response: {e}",
                "merkle_root": merkle_root}


def trace_lineage(root, _seen=None):
    _seen = _seen or set()
    if root in _seen:
        return {"root": root, "resolved": False, "note": "cycle"}
    _seen.add(root)
    rr = httpx.get(f"{API_BASE}/trace/resolve/{root}", timeout=TIMEOUT)
    if rr.status_code == 404:
        return {"root": root, "resolved": False, "note": "unresolved frontier"}
    rr.raise_for_status()
    payload = rr.json()["payload"]
    v = verify_root(root)
    node = {
        "root": root, "resolved": True, "door": payload.get("produced_by"),
        "hash_binds": hashlib.sha256(_canon(payload)).hexdigest() == v.get("data_hash"),
        "anchored": v.get("verified") is True,
        "block_height": v.get("block_height"), "derived_from": [],
    }
    for ref in payload.get("derived_from", []):
        pv = verify_root(ref["merkle_root"])
        node["derived_from"].append({
            "relationship": ref.get("relationship", "derivedFrom"),
            "edge_verified": pv.get("data_hash") == ref["data_hash"],
            "node": trace_lineage(ref["merkle_root"], _seen),
        })
    return node


def lineage_valid(node) -> bool:
    ok = bool(node.get("resolved") and node.get("hash_binds") and node.get("anchored"))
    for e in node.get("derived_from", []):
        ok = ok and e.get("edge_verified") and lineage_valid(e["node"])
    return ok


_STAMP_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema": {"type": "string"},
        "merkle_root": {"type": "string"},
        "data_hash": {"type": "string"},
        "wallet": {"type": "string"},
        "zk_commitment": {"type": ["string", "null"]},
        "block_height": {"type": ["integer", "null"],
                         "description": "Markovian chain height where the commitment was recorded (the Markovian chain block, not a Bitcoin block)."},
        "stamped_at": {"type": "string"},
        "verify": {"type": "string"},
        "attestation": {"type": "string"},
    },
    "required": ["schema", "merkle_root", "data_hash", "wallet",
                 "stamped_at", "verify", "attestation"],
}

TOOLS = [
    types.Tool(
        name="markovian_stamp",
        title="Markovian Provenance Stamp",
        description=(
            "Commit any data (an AI output, a decision, a record) to the Markovian "
            "chain and get back a verifiable, tamper-evident provenance stamp "
            "(canonical markovian-provenance/v1). It proves the data existed and was "
            "committed at this time; it does NOT assert the data is correct (provenance, "
            "not truth). No wallet, account, or funding is required, the first stamp just "
            "works, and only the SHA-256 hash of your data is sent to the public API, the "
            "raw data is never stored. The returned merkle_root is the handle: save it, then "
            "call markovian_verify(merkle_root) to prove integrity later, or pass prior "
            "stamps in derived_from to build a lineage you can walk with markovian_trace. "
            "Typical use: stamp an agent output the moment it is produced, so anyone can "
            "later confirm it was not altered."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "data": {"type": "string",
                         "description": "Exact bytes/string to stamp. Hashed server-side; raw data is not stored."},
                "wallet": {"type": "string",
                           "description": "Optional. Omit and the protocol mints an ephemeral committer for you. Provide one to attribute the stamp or to burn from your own MKV balance."},
                "label": {"type": "string",
                          "description": "Optional human label for the stamp."},
                "derived_from": {
                    "type": "array",
                    "description": "Optional lineage. A list of prior stamps this output was derived from, each {merkle_root, data_hash}. Bound inside the committed bytes so the link is tamper-evident; the payload is published so markovian_trace can walk it.",
                    "items": {"type": "object",
                              "properties": {"merkle_root": {"type": "string"},
                                             "data_hash": {"type": "string"},
                                             "relationship": {"type": "string"}},
                              "required": ["merkle_root", "data_hash"]},
                },
            },
            "required": ["data"],
            "additionalProperties": False,
        },
        outputSchema=_STAMP_OUTPUT_SCHEMA,
        annotations=types.ToolAnnotations(
            title="Markovian Provenance Stamp",
            readOnlyHint=False, destructiveHint=False,
            idempotentHint=False, openWorldHint=True,
        ),
    ),
    types.Tool(
        name="markovian_verify",
        title="Markovian Verify",
        description=(
            "Independently verify a Markovian stamp by its merkle_root against the public "
            "verifier, with no key or account. Use this to confirm a stamped record existed "
            "at its claimed time and has not been altered since. Returns the verifier payload "
            "(type:external_stamp, verified:true when the commitment matches; an unknown or "
            "edited merkle_root returns verified:false). Read-only: it calls the public verify "
            "endpoint, so anyone can run it, including a party who does not trust the stamper."
        ),
        inputSchema={
            "type": "object",
            "properties": {"merkle_root": {"type": "string",
                                           "description": "merkle_root to verify."}},
            "required": ["merkle_root"],
            "additionalProperties": False,
        },
        annotations=types.ToolAnnotations(
            title="Markovian Verify", readOnlyHint=True, openWorldHint=True),
    ),
    types.Tool(
        name="markovian_trace",
        title="Markovian Trace",
        description=(
            "Walk and verify a stamp's full provenance lineage by merkle_root. Use this "
            "when a stamp was created with derived_from links, to map what an output was "
            "built from. Returns a MAP of the graph (not a yes/no verdict): each node carries "
            "hash_binds and anchored, each edge carries edge_verified, and `valid` is true "
            "only if every node and edge checks out. A node whose payload was never published "
            "is an unresolved frontier (resolved:false). Read-only. Provenance, not truth."
        ),
        inputSchema={
            "type": "object",
            "properties": {"merkle_root": {"type": "string",
                                           "description": "root of the stamp to trace."}},
            "required": ["merkle_root"],
            "additionalProperties": False,
        },
        annotations=types.ToolAnnotations(
            title="Markovian Trace", readOnlyHint=True, openWorldHint=True),
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
    try:
        if name == "markovian_stamp":
            obj = await anyio.to_thread.run_sync(
                lambda: stamp_output(arguments["data"], arguments.get("wallet"),
                                     arguments.get("label"), arguments.get("derived_from"))
            )
            result = types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(obj))],
                structuredContent=obj, isError=False,
            )
            # The SDK silently drops a `meta=` constructor kwarg (no populate_by_name);
            # set the field by attribute so it serializes as _meta.
            result.meta = {PROV_KEY: obj}
            return result

        if name == "markovian_verify":
            vr = await anyio.to_thread.run_sync(
                lambda: verify_root(arguments["merkle_root"]))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(vr))],
                structuredContent=vr, isError=False)

        if name == "markovian_trace":
            tr = await anyio.to_thread.run_sync(
                lambda: trace_lineage(arguments["merkle_root"]))
            out = {"lineage": tr, "valid": lineage_valid(tr)}
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(out))],
                structuredContent=out, isError=False)

        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Unknown tool: {name}")],
            isError=True)
    except Exception as e:  # noqa: BLE001
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Error: {e}")],
            isError=True)


async def _run() -> None:
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    anyio.run(_run)


if __name__ == "__main__":
    main()
