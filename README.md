# markovian-mcp

Bitcoin-anchored, independently verifiable provenance for AI outputs, exposed as [MCP](https://modelcontextprotocol.io) tools.

Trust the emitter? No. **Prove the emitter.** Commit an output to a canonical root, verify it later by pure recomputation, and trace its lineage. No operator to trust; verification is offline.

## Tools

- **`markovian_stamp(content)`** — compute the canonical commitment root for an output. JSON is canonicalized with RFC 8785 (JCS), other text verbatim, then SHA-256 hashed. This root is what Markovian anchors to Bitcoin.
- **`markovian_verify(content, canonical_root)`** — recompute the root and check it. One changed byte fails the check.
- **`markovian_trace(receipts_json)`** — walk a lineage of stamps back to its origin.

## Install

```bash
pip install markovian-mcp
```

## Configure (Claude Desktop / Cursor / Claude Code)

```json
{
  "mcpServers": {
    "markovian": {
      "command": "markovian-mcp"
    }
  }
}
```

## Verify offline

`markovian_stamp` and `markovian_verify` are pure functions. Anyone can recompute a root over the same bytes and get the same answer, with nothing trusted from us. Learn more at [markovianprotocol.com](https://markovianprotocol.com).

Apache-2.0.
