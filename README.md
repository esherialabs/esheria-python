# Esheria CLI And MCP

Installable command-line and MCP tools for the Esheria Regulatory Pack API.

Global, citation-backed regulatory intelligence for explicit published packs.
Discover current readiness, select the intended jurisdiction and pack, and
preserve citations, versions, limitations, and trace IDs across CLI, Python,
and MCP workflows. Esheria provides regulatory intelligence, not legal advice.

<!-- mcp-name: io.github.esherialabs/esheria -->

The package exposes two commands:

```bash
esheria --help
esheria-mcp --help
esheria mcp serve --help
```

Version `1.2.2` is the production/stable public release. The CLI, Python
client, and MCP software distributed in the `esheria` Python package are
licensed under the Apache License 2.0. Hosted API/MCP access, regulatory data,
service outputs, and Esheria trademarks are not licensed under Apache-2.0;
they remain governed by the [Esheria Terms of Service](https://esheria.ai/terms),
[Privacy Policy](https://esheria.ai/privacy), and any applicable customer
agreement. See `LICENSE` and `NOTICE` for the exact boundary.

## CLI Quickstart

1. Create a data API token in the Esheria dashboard.
2. Install the command. `pipx` is recommended because it keeps command-line
   tools isolated from project dependencies:

```bash
pipx install esheria
```

If you do not use `pipx`, use normal `pip`:

```bash
python3 -m pip install esheria
```

3. Configure your shell. Put these in your terminal for a one-off test, or in
   `~/.zshrc`, `~/.bashrc`, or your shell profile to keep them:

```bash
export ESHERIA_API_BASE_URL="https://api.esheria.ai"
export ESHERIA_API_KEY="<client-api-key>"
```

PowerShell:

```powershell
$env:ESHERIA_API_BASE_URL = "https://api.esheria.ai"
$env:ESHERIA_API_KEY = "<client-api-key>"
```

`ESHERIA_API_TOKEN` is also accepted as an alias when `ESHERIA_API_KEY` is
unset.

Do not commit API keys. The CLI and MCP server read credentials from
environment variables or command-line flags and redact API key values from
diagnostic output. Prefer the environment variable: `--api-key` can be exposed
through shell history or the operating-system process list.

4. Confirm the API is reachable:

```bash
esheria --version
esheria health --format json
esheria ready --format json
```

5. Discover packs, choose a `domain_pack_id`, then pass that pack ID to
   pack-specific commands:

```bash
esheria packs list --format json
export ESHERIA_PACK_ID="UK-DATA-PROTECTION-PRIVACY"
esheria packs inspect "$ESHERIA_PACK_ID" --format json
esheria packs versions "$ESHERIA_PACK_ID" --format json
esheria packs diff "$ESHERIA_PACK_ID" --format json
esheria packs change-events "$ESHERIA_PACK_ID" --format json
esheria obligations list "$ESHERIA_PACK_ID" --limit 3 --format json
esheria penalties list "$ESHERIA_PACK_ID" --limit 5 --format json
esheria legal-review audit "$ESHERIA_PACK_ID" --limit 5 --format json
```

Output flags can be placed globally or on a leaf command:

```bash
esheria --format json packs list
esheria packs list --format json
```

Use `esheria --help` and `<group> --help` to discover the full command tree.
The CLI includes source-watch operations, graph coverage/rebuild operations,
workspace-scoped customer lifecycle commands, and workspace/token/billing
management commands in addition to the read workflows above.

Workspace, token, and billing commands require a management token. Normal
dashboard-created and OAuth connector tokens carry only `regulatory:read`.
State-changing regulatory workflows require an explicitly created operator
data token with one or more of `monitoring:write`, `graph:write`, or
`customer:write`; `regulatory:read` alone is rejected. For example:

```bash
esheria tokens create \
  --name "Monitoring operator" \
  --scope regulatory:read \
  --scope monitoring:write \
  --pack UK-DATA-USE-AND-ACCESS
```

The dashboard remains the recommended place for self-serve workspace, token,
billing, and subscription administration. Keep operator tokens short-lived and
grant only the scopes and pack entitlements they require.

The CLI and MCP server are catalog-first: users list packs and then call tools
with the explicit pack ID they want. `ESHERIA_DEFAULT_PACK_ID` is an optional
client preference, not a server-side jurisdiction default.

The CLI reports the API's readiness labels, limitations, citations, and trace
IDs; preserve them in downstream workflows. Published packs may represent a
reviewed subset of the full legal corpus, and evaluator-gated claim verification
is not available for every pack. Esheria output is regulatory intelligence, not
legal advice or a substitute for qualified counsel.

## Hosted MCP

Production MCP uses the hosted Esheria endpoint:

```text
https://mcp.esheria.ai/mcp
```

Use this endpoint for normal customer onboarding. It avoids local Python, `uvx`,
virtual environments, and package discovery on the user's machine.

Claude Directory hosts use OAuth. Other agent hosts send a dashboard-created
Esheria data token as a bearer token or `X-API-Key`. The hosted MCP server
introspects the credential before initialization and calls the Regulatory Pack
API with it, so billing, pack entitlements, trace IDs, and published-only
behavior remain centralized. Invalid and management-only credentials cannot
enumerate tools.

## Codex MCP

Set the token where Codex can read it:

```bash
export ESHERIA_API_KEY="<client-api-key>"
```

Edit `~/.codex/config.toml` and add:

```toml
[mcp_servers.esheria]
url = "https://mcp.esheria.ai/mcp"
bearer_token_env_var = "ESHERIA_API_KEY"
```

Restart Codex, then call `esheria_health`, `esheria_ready`, and
`esheria_list_packs`.

## Local MCP Fallback

For local development, or for agent hosts that do not support remote MCP URLs,
you can run the stdio server yourself:

```bash
esheria-mcp serve --stdio
```

Operator-only HTTP transport command:

```bash
ESHERIA_API_BASE_URL="https://api.esheria.ai" \
  esheria-mcp serve --http --host 127.0.0.1 --port 8081 --path /mcp
```

Production is already deployed at `https://mcp.esheria.ai/mcp`; end users
should not run this command.

The hosted OAuth profile exposes a read-only 20-tool catalog for health, readiness, pack discovery, obligations, applicability, claim verification, versions, diffs, change events, filing calendars, evidence, penalties, audit metadata, relationship queries, exports, and citation context. Normal API data tokens expose 29 safe read/read-like tools. Operator data tokens add only mutations authorized by `monitoring:write`, `graph:write`, and/or `customer:write`, up to the complete 37-tool catalog. Every mutation
also requires `confirm=true`; OAuth Directory sessions remain read-only.

The hosted service uses the official MCP SDK and current Streamable HTTP.
Successful tools mirror bounded JSON in text content and `structuredContent`,
with `trace_id` and `mcp` truncation metadata. Use the API or CLI when a
complete large export is needed.

Use stdio only for hosts that do not support remote MCP URLs:

```toml
[mcp_servers.esheria]
command = "uvx"
args = ["--from", "esheria", "esheria-mcp", "serve", "--stdio"]
env = { ESHERIA_API_BASE_URL = "https://api.esheria.ai", ESHERIA_API_KEY = "<client-api-key>" }
```

## Claude Code

Use Claude Code's remote MCP setup when your installed version exposes it:

- URL: `https://mcp.esheria.ai/mcp`
- Authorization: `Bearer <client-api-key>`

If your Claude Code version only supports local stdio MCP servers, run this
fallback once from a terminal:

```bash
claude mcp add --scope user --transport stdio \
  --env ESHERIA_API_BASE_URL=https://api.esheria.ai \
  --env ESHERIA_API_KEY=<client-api-key> \
  esheria -- uvx --from esheria esheria-mcp serve --stdio
```

Then run:

```bash
claude mcp list
```

Start or restart Claude Code and ask it to use the Esheria MCP tools.

## Claude Desktop

Use Claude Desktop's remote MCP setup when your installed version exposes it:

- URL: `https://mcp.esheria.ai/mcp`
- Authorization: `Bearer <client-api-key>`

If your Claude Desktop version only supports local stdio MCP servers, use the
fallback below.

Open the Claude Desktop MCP config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Add or merge this object:

```json
{
  "mcpServers": {
    "esheria": {
      "command": "uvx",
      "args": ["--from", "esheria", "esheria-mcp", "serve", "--stdio"],
      "env": {
        "ESHERIA_API_BASE_URL": "https://api.esheria.ai",
        "ESHERIA_API_KEY": "<client-api-key>"
      }
    }
  }
}
```

Restart Claude Desktop after saving the file.
