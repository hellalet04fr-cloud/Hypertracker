# NotebookLM MCP (roomi-fields/notebooklm-mcp)

Google NotebookLM over MCP: citation-backed Q&A, Studio generation (audio/video/report),
and multi-account rotation. Package: [`@roomi-fields/notebooklm-mcp`](https://github.com/roomi-fields/notebooklm-mcp).

## How it's wired in this repo

The server is registered as a project MCP server in [`.mcp.json`](../.mcp.json) at the repo
root. Any MCP-aware client that reads project config (Claude Code, Cursor, Codex) will pick it
up automatically. It runs the server on demand via `npx`, pinned to a specific version so it
doesn't drift.

## One-time authentication (required, do this locally)

The server drives NotebookLM through a real browser session, so you must sign in to Google
once. This step is **interactive** and opens a visible Chrome window — it cannot be done from a
headless/remote agent session, only from your own terminal:

```bash
npx -y @roomi-fields/notebooklm-mcp@3.1.2 setup-auth
```

A Chrome window opens for Google sign-in. The saved session is reused by the MCP server on
subsequent runs. Requires Node.js >= 18.

## Alternative: install as a Claude Code plugin

Instead of (or in addition to) the checked-in `.mcp.json`, you can install it via the
roomi-fields plugin marketplace from an interactive Claude Code CLI:

```
/plugin marketplace add roomi-fields/claude-plugins
/plugin install notebooklm@roomi-fields
```

The marketplace install registers the MCP server automatically. You still need to run the
`setup-auth` step above once.

## Optional environment variables

- `NOTEBOOKLM_UI_LOCALE` — NotebookLM UI locale (default `en` here).
- `NOTEBOOKLM_CONTENT_LANGUAGE` — generated-content language (default `en` here).

Adjust these in `.mcp.json` to your preferred language.
