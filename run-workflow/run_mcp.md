# Calling MCP Tools Directly

In rare cases, you may want to call an MCP server directly — for example, to test a single tool, inspect available tools, or debug a specific MCP endpoint.

`wf tool` wraps [mcp2cli](https://github.com/punkpeye/mcp2cli) and forwards all arguments as-is.

## Step 1: Find Tools by Keyword

First, discover available MCP tools that match your needs.

```sh
wf tool query "<QUERIES>" [--limit LIMIT] [--user-intent USER_INTENT]
```

- `QUERIES`: Semicolon-separated search terms, e.g. `"fetch news;web scraping;sentiment analysis"`.
- `--limit`: Maximum number of results (default: 64).
- `--user-intent`: Optional sentence describing what you want to accomplish.

You can also browse a predefined tool set:

```sh
wf tool set <TOOL_SET> [--limit LIMIT]
```

Available sets: `dataframe`, `ai_field_template`, `browserscraper`, `Others`.

## Step 2: Get Tool Specs and MCP Server URL

Once you've found the tools you need, fetch their full specifications — including parameters and the MCP server URL required for direct invocation.

```sh
wf tool info "<TOOL_IDS>"
```

- `TOOL_IDS`: Semicolon-separated IDs from Step 1, e.g. `"tool_id_1;tool_id_2"`.

The output includes the MCP server URL for each tool, which you'll use in Step 3.

## Step 3: Connect to the MCP Server and Call Tools

With the MCP server URL from Step 2, you can now interact with the server directly.

```sh
# List available tools on an MCP server
wf tool --mcp https://mcp.example.com/sse --list

# Call a tool
wf tool --mcp https://mcp.example.com/sse search --query "test"

# With auth header
wf tool --mcp https://mcp.example.com/sse --auth-header "x-api-key:sk-..." \
  query --sql "SELECT 1"

# Force a specific transport (skip streamable HTTP fallback)
wf tool --mcp https://mcp.example.com/sse --transport sse --list

# Search tools by name or description
wf tool --mcp https://mcp.example.com/sse --search "task"
```

For the full list of options, see `wf tool --help`.
