# markovian-mcp

Bitcoin-anchored, independently verifiable provenance for AI outputs, exposed as [MCP](https://modelcontextprotocol.io) tools.

Trust the emitter? No. **Prove the emitter.** Commit an output to the Markovian chain the moment it is produced, and anyone can later confirm it existed then and has not been altered since, without trusting you, us, or any operator.

A stamp proves **provenance, not truth**. It proves the data was committed at a time. It does not assert the data is correct.

## Two doors, one server

This package is the **stdio** door. The **hosted HTTP** door is the same server, with the same tool names, the same parameters and the same returned objects:

```
https://api.markovianprotocol.com/mcp/
```

Code written against one works unchanged against the other. Pick a transport, not a semantics. (The trailing slash matters: `/mcp` returns a redirect that some clients will not follow.)

## Tools

- **`markovian_stamp(data, wallet?, label?, derived_from?)`** — commit `data` to the Markovian chain and get back a verifiable, tamper-evident stamp (`markovian-provenance/v1`). Only the SHA-256 of your data is sent; the raw data is never stored. No wallet or account is needed, the first stamp just works. The returned `merkle_root` is the handle.
- **`markovian_verify(merkle_root)`** — check a stamp against the public verifier. No key, no account. An unknown or edited root returns `verified: false`. Anyone can run it, including a party who does not trust the stamper.
- **`markovian_trace(merkle_root)`** — walk a stamp's `derived_from` lineage. Returns a map of the graph, not a verdict: every node carries `hash_binds` and `anchored`, every edge carries `edge_verified`, and `valid` is true only if all of them check out.

Lineage links are bound *inside* the committed bytes, so an edge cannot be added or removed after the fact without changing the root.

## Install

```bash
pip install markovian-mcp
```

## Configure (Claude Desktop / Cursor / Claude Code)

Local, over stdio:

```json
{
  "mcpServers": {
    "markovian": {
      "command": "markovian-mcp"
    }
  }
}
```

Or point at the hosted server instead, with no install:

```json
{
  "mcpServers": {
    "markovian": {
      "url": "https://api.markovianprotocol.com/mcp/"
    }
  }
}
```

## Verify without trusting us

Verification is a plain public GET. Nothing in it depends on this package, this server, or our good behaviour:

```bash
curl https://api.markovianprotocol.com/verify/<merkle_root>
```

Change one byte of the stamped data and the root no longer matches. That is the whole guarantee, and it is checkable by someone who thinks we are lying.

More at [markovianprotocol.com](https://markovianprotocol.com).

## Changelog

**0.2.0** — breaking. The tools now speak to the live chain and match the hosted
server exactly. Previously this package shipped local-only hash helpers whose
names collided with the hosted server's but whose signatures and semantics did
not (`markovian_stamp(content)` returning a locally computed digest, versus
`markovian_stamp(data)` returning a chain commitment). An agent could not move
between the two. There is now one set of tools with one meaning. The old
`canonicalization` field also claimed RFC 8785 (JCS) while implementing sorted-key
`json.dumps`, which is not JCS; that claim is gone rather than restated.

Apache-2.0.
