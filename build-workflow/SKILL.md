---
name: build-dataflow
description: "Defines and validates dataflow/workflow JSON files. Use when creating, editing, or validating dataflow definitions, or discovering MCP tools via the wf CLI."
---

# Dataflow Definition and Validation

A dataflow (also called workflow) is a data processing pipeline defined in JSON format. It decomposes a data task into multiple executable flows based on the DataFrame paradigm, following an "acquire → analyze → act" pattern.

## How Dataflows Are Defined

A dataflow is defined as a JSON file with the following structure:

- **title**: A descriptive title for the workflow.
- **objective**: What the workflow aims to accomplish.
- **variables**: A list of configurable parameters (scalar, series, or dataframe) with default values and descriptions.
- **flows**: An ordered list of flow steps. Each flow has an `id`, `description`, `depends_on`, `operation`, `input`, and `output`. Supported flow types include:
  - `ToolCallFlow` — Direct MCP tool invocations.
  - `MapFlow` — Apply a tool to each row/item (field template pattern).
  - `FilterFlow` — Filter dataframe rows by conditions.
  - `ApplyFlow` — Apply LLM calls for text analysis/generation.
  - `SwitchFlow` — Conditional branching based on data conditions.
  - `ConfluenceFlow` — Merge outputs from different switch branches.
  - `LoopFlow` — Iterative processing (while, for_each, repeat).
  - `HumanInteractionFlow` — Pause for user input/approval.
- **output**: The final output reference(s) of the workflow.

The detailed specification for each flow type, argument types, output types, data type notation, and best practices is documented in `spec.md`.

## CLI Usage

The CLI tool `wf` provides commands for validating dataflow JSON files and discovering MCP tools.

### Validate a Dataflow

```sh
wf check <INPUT_FILE>
```

Validates the dataflow JSON file against the schema. Returns exit code 0 on success and 1 on failure with error details. Use the error messages to adjust your dataflow definition until validation passes.

### Search for MCP Tools

```sh
wf tool query "<QUERIES>" [--limit LIMIT] [--user-intent USER_INTENT]
```

Search for available MCP tools by semicolon-separated functional queries. Use different queries to find the most suitable tools for your dataflow.

- `QUERIES`: Semicolon-separated search terms, e.g. `"fetch news;web scraping;sentiment analysis"`.
- `--limit`: Maximum number of results (default: 64).
- `--user-intent`: Optional sentence describing what you want to accomplish.

### Get Tool Details

```sh
wf tool info "<TOOL_IDS>"
```

Fetch detailed specifications (parameters, descriptions, usage) for specific tools by semicolon-separated tool IDs. Use this when you know the tool ID and need its full parameter spec.

- `TOOL_IDS`: Semicolon-separated IDs, e.g. `"tool_id_1;tool_id_2"`.

### List Tools from a Tool Set

```sh
wf tool set <TOOL_SET> [--limit LIMIT]
```

Get tools from a predefined tool set. Available sets: `dataframe`, `ai_field_template`, `browserscraper`, `Others`.

- `--limit`: Maximum number of tools (default: 64).

## File Location and Naming

Unless the user specifies otherwise, create dataflow JSON files under the `workflow/` directory in the current working directory. Use descriptive kebab-case file names, e.g. `workflow/news-sentiment-analysis.json`, `workflow/product-price-monitor.json`.

## IMPORTANT: Read the Spec First

**Before creating or editing any dataflow JSON file, you MUST read `spec.md` (located in the same directory as this skill file) in full.** The spec contains the complete and authoritative definition of every flow type, argument format, output format, data type notation, field template syntax, and best practices. Skipping the spec will lead to invalid dataflow definitions.

## Typical Workflow

1. **Read `spec.md` thoroughly** to understand all flow types, data types, and conventions.
2. Use `wf tool query` and `wf tool set` to discover available MCP tools for your task.
3. Use `wf tool info` to get detailed parameter specs for selected tools.
4. Define your dataflow in a JSON file following the spec (save to `workflow/` by default).
5. Run `wf check <file.json>` to validate the dataflow structure.
6. Fix any errors reported by `wf check` and re-validate until the dataflow passes.
