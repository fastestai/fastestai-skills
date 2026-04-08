---
name: run-workflow
description: "Runs a dataflow/workflow JSON file or workflow ID via the wf CLI, or calls MCP tools directly. Use when executing, testing, or iterating on dataflow definitions locally or remotely, or when calling MCP tools."
---

# Running a Dataflow

Use `wf run` to execute a local dataflow JSON file or a remote workflow ID.

```sh
wf run <WORKFLOW_ID_OR_FILE>
```

## Running by Workflow ID

`wf run` first checks whether the argument is a local file path. If the file exists, it runs that local JSON file exactly as before.

If the path does not exist, `wf run` treats the argument as a workflow ID, fetches the workflow definition from the workflow detail API, extracts `result.data`, and runs that workflow without saving it locally first.

Examples:

```sh
# Run a local workflow file
wf run workflow.json

# Run a remote workflow by workflow ID
wf run 694e206fc1c0b24dc831ad8b
```

## Local vs Remote

- **Remote** (default): `wf run <WORKFLOW_ID_OR_FILE>` delegates execution to the server.
- **Local**: `wf run <WORKFLOW_ID_OR_FILE> --mode local` runs directly on the local machine and is useful for debugging and faster iteration.

Use remote by default. Use local mode when you need debugging or faster iteration.

## Passing Variable Overrides

Dataflow variables can be overridden directly as CLI flags using their short name (the last segment of `variable:type:name`). Values are parsed as JSON; plain strings are also accepted.

```sh
# Override a scalar variable
wf run workflow.json --prompt "hello world"

# Override a dataframe variable
wf run workflow.json --data '[{"col1": 1, "col2": 2}]'

# Override a series variable
wf run workflow.json --tags '["tag1", "tag2"]'

# Multiple overrides
wf run workflow.json --prompt "test" --limit 10 --data '[{"a":1}]'
```

If a variable is named `variable:scalar:prompt` in the dataflow JSON, use `--prompt` on the CLI. Unknown parameter names will produce an error listing valid variable names.

## Results and Logs

After execution, outputs are saved automatically:

- **Result**: `output/<timestamp>.json` (dataframe/series) or `output/<timestamp>.txt` (scalar)
- **Log**: `log/<timestamp>.log`, with the same timestamp prefix as the result file

A status message is printed to stderr on both success and failure, indicating the result path and log path.

## Notes

- Avoid using `--task-id` unless you know exactly what you are doing.
- For other options, see `wf run --help`.

# Calling MCP Tools Directly

In rare cases, you may want to call an MCP server directly — for example, to test a single tool or inspect available tools. See `run_mcp.md` in this directory for usage.
