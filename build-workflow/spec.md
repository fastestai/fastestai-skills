# Dataflow Specification

A dataflow is a data processing pipeline composed of multiple executable flows based on the DataFrame paradigm. The process is fundamentally a **sheet-building workflow** that follows the field template pattern:
- Identify what columns (fields) need to be populated in the data sheet
- Use map operations to systematically fill the sheet **column by column, row by row**
- Each map operation applies MCP tools and field template tools to populate specific fields

## Dataflow JSON Structure

A dataflow is defined as a JSON object with the following top-level fields:

```json
{
  "id": "auto-generated UUID",
  "title": "Descriptive title (can reference variable:scalar: variables)",
  "objective": "What the workflow aims to accomplish",
  "variables": [
    {
      "name": "variable:scalar|series|dataframe:variable_name",
      "default_value": "default value (any type)",
      "description": "Brief question for this variable"
    }
  ],
  "flows": [
    // Ordered list of flow steps (see Flow Types below)
  ],
  "output": ["scalar|series|dataframe:output_name", "..."] // Must be an array, even for a single output
}
```

- **id** (`str`): Auto-generated UUID identifier.
- **title** (`str`): Descriptive title for the workflow.
- **objective** (`str`): What the workflow aims to accomplish.
- **variables** (`list[Variable]`): Configurable parameters with `name`, `default_value`, and `description`.
- **flows** (`list[Flow]`): Ordered list of flow steps. Each flow has `id`, `description`, `depends_on`, `operation`, `input`, and `output`. Supported types: `ToolCallFlow`, `MapFlow`, `FilterFlow`, `ApplyFlow`, `SwitchFlow`, `ConfluenceFlow`, `LoopFlow`, `HumanInteractionFlow`.
- **output** (`list[str] | null`): Final output reference(s) of the workflow. Must be an array even if there is only one output, e.g. `["dataframe:result"]`.

## Defining Dataflow

### Core Data Types

The dataflow system operates on three fundamental data types:
- **Scalar**: Single values (string, number, boolean, etc.)
- **Series**: One-dimensional arrays of data (like pandas Series)
- **DataFrame**: Two-dimensional tabular data with named columns

**Value Interpretation Rules:**

When a value is declared as `scalar`, it is kept as-is regardless of its structure — a `list`, `dict`, or `list[dict]` assigned to a scalar remains the raw value untouched. However, the same structures are interpreted differently when declared as `series` or `dataframe`:

- **scalar**: always stored verbatim, no conversion. `["a", "b"]`, `{"k": "v"}`, `[{"name": "Alice"}, ...]` all remain the raw value.
- **series**: `list[...]` → each element becomes a row. E.g. `["a", "b", "c"]` becomes a 3-element series.
- **dataframe**: `list[dict]` → each dict becomes a row, keys become columns. E.g. `[{"name": "Alice"}, {"name": "Bob"}]` becomes a 2-row dataframe with column `name`.

### Data Type Notation

Use explicit type notation in input/output specifications:

- `scalar:data_name` - for single values
- `series:data_name` - for one-dimensional data
- `dataframe:data_name` - for tabular data

### Data Formatting Notation

Use `${}` syntax to format data within strings

- `${scalar:data_name}` - for single values
- `${series:data_name}` - for one-dimensional data
- `${dataframe:data_name}` - for tabular data

Example usage: "Analyze the following data: ${dataframe:input_data} and ${series:series_name}"


### Flow Types and Operations

#### 1. Tool Call Operations
Direct tool invocations that transform data:
<code lang="json">
{
  "type": "tool_call", // Literal "tool_call"
  "tool": {
    "id": "tool_name",
    "arguments": [...]
  }
}
</code>

Input: null, scalar, series, or dataframe
Output: DataframeOutput, SeriesOutput, or ScalarOutput (depending on tool)

#### 2. Map Operations - The Field Template Pattern
Apply a tool to each item in a series or each row in a dataframe.

<code lang="json">
{
  "type": "map", // Literal "map"
  "tool": {
    "id": "tool_name",
    "arguments": [
      {
        "name": "param_name",
        "type": "map_item",
        "value": "dataframe:source_data.column_name or series:series_name"
      }
    ]
  }
}
</code>

Input: series
Output: DataframeOutput, SeriesOutput, or JoinOutput (depending on operation result)

**Field Template Approach**: This is the core mechanism for filling result sheets column by column, row by row. Each map operation represents filling a specific field (column) in your result sheet. Use MCP tools and field template tools to systematically populate each field with the appropriate data for each row.

#### 3. Apply Operations
Apply custom functions (usually LLM calls) to aggregate or transform data:
<code lang="json">
{
  "type": "apply", // Literal "apply"
  "function": {
    "type": "llm_call",
    "prompt": "Analysis the following data: ${dataframe:input_data} and ${series:series_name}"
  }
}
</code>

Input: scalar, series, dataframe, or multiple inputs
Output: ScalarOutput (plain text response from LLM)

Currently ONLY LLM calls are supported.

**CRITICAL**: LLM calls are designed for text analysis and generation tasks only, and cannot use or call other MCP tools. **NEVER use LLM calls to generate structured output with multiple cells or fields** - they should only generate single text values. Do not use LLM calls for complex DataFrame or Series processing, data extraction, or other operations when direct column access is available. For structured data creation, use the field template pattern with map operations and appropriate MCP tools to fill each column individually.

##### Writing Good Prompts

When writing prompts for `llm_call`, use this format:

You are a [domain expert/analyst/specialist] with expertise in [relevant field]. Your task is to [specific objective description].

## Data Context (If no data is provided, skip this section)

**[Description of first data source]:**

${dataframe:data_source_name}

**[Description of second data source]:**

${series:series_name}

**[Description of additional context if needed]:**

${scalar:context_variable}

## Output Format

[Clear description of expected text output format and requirements]

**Example:**

You are a market research analyst with expertise in social media trends. Your task is to analyze search results and social media data to identify emerging topics and sentiment patterns.

## Data Context

**Search results from Google News API:**

${dataframe:news_results}

**Recent tweets from Twitter search:**

${series:tweet_content}

## Output Format

Provide a detailed analysis including:
1. Top 3 emerging topics with evidence
2. Overall sentiment summary
3. Key insights and recommendations

### Output Specifications

By default, operations output data with simple string references like "dataframe:output_name" or "scalar:result". However, for more advanced data manipulation, you can use structured output specifications:

#### 1. ScalarOutput - Create New Scalar Value
Creates a new scalar value from the operation result:

<code lang="json">
"output": {
  "type": "scalar",
  "id": "scalar:result_name"
}
</code>

This creates a new scalar value from the operation output.

#### 2. SeriesOutput - Create New Series
Creates a new series from the operation result:

<code lang="json">
"output": {
  "type": "series",
  "id": "series:series_name"
}
</code>

This creates a new series containing the operation output.

#### 3. DataframeOutput - Create New DataFrame with Column Selection
Creates a new dataframe by selecting specific columns from the operation result and optionally renaming them:

<code lang="json">
"output": {
  "type": "dataframe",
  "id": "dataframe:new_df_name",
  "select_columns": ["original_column1", "original_column2"]
}
</code>

This creates a new dataframe by selecting specific columns from the operation result.

**Rules:**
- `select_columns` is optional and can be null to include all columns
- Only specified columns in `select_columns` will be included in the output dataframe
- Selected columns retain their original names

#### 4. JoinOutput - Join Results Back (Map Operations Only)

**IMPORTANT**: JoinOutput can ONLY be used with map operations. It creates a NEW dataframe by combining specific columns from the map operation results with the original input dataframe to produce a completely new dataframe.

**FIELD TEMPLATE PATTERN**: JoinOutput perfectly aligns with the field template approach - it allows you to systematically populate new fields (columns) in your result dataframe while preserving the original structure. This is the PREFERRED pattern when the dataframe size remains unchanged and you're adding new computed fields.

<code lang="json">
"output": {
  "type": "join",
  "id": "dataframe:enriched_results",
  "select_columns": ["result_column1", "result_column2"],
  "rename_columns": {
    "result_column1": "new_column1",
    "result_column2": "new_column2"
  }
}
</code>

This creates a NEW dataframe by taking the specified columns from each map operation result and joining them to the original input dataframe. The result contains all original columns plus the renamed columns from the join operation.

**Rules:**
- `select_columns` is required to specify which columns from the map operation result to include
- `rename_columns` keys must be a subset of `select_columns`
- Only specified columns in `select_columns` will be joined with the original input dataframe

**CRITICAL**: After join operations, you MUST use the renamed column names specified in the `rename_columns` mapping. Never use the original column names from the map operation results.

**WHEN TO USE JOINOUTPUT:**
- When dataframe size remains unchanged (same number of rows)
- When implementing field template pattern to populate new columns
- When you want to preserve original data structure while adding computed fields
- When building result sheets column by column with map operations

**PREFER JOINOUTPUT over DataframeOutput in Map** in these scenarios as it maintains data integrity and follows the field template methodology.

**Usage Example:**
- Input dataframe has columns: ["id", "name", "description"]
- Map operation processes each row and returns: {"sentiment": "positive", "score": 0.8, "keywords": ["AI", "tech"]}
- JoinOutput with `select_columns: ["sentiment", "score"]` and `rename_columns: {"sentiment": "sentiment_analysis", "score": "confidence_score"}`
- **IMPORTANT**: The new dataframe contains columns ["id", "name", "description", "sentiment_analysis", "confidence_score"]
- **Subsequent operations must use "sentiment_analysis" and "confidence_score", NOT "sentiment" and "score"**

#### 5. DataFrame Manipulation Tools

The system provides comprehensive DataFrame manipulation tools for data processing and transformation:

**Data Initialization**: Create DataFrames from structured data (arrays of objects) with automatic column detection and shape analysis.

**Data Filtering**: Apply single or multiple conditions to filter DataFrame rows using various operators (equals, greater than, contains, null checks, regex matching, etc.) with AND/OR logic combinations.

**Formula Application**: Apply Excel-like formulas to DataFrame columns using either simple column name references or Excel-style cell references (A1, B1, etc.). Supports mathematical operations, conditional logic, and built-in functions.

**Data Combination**:
- Concatenate multiple DataFrames vertically with optional duplicate removal
- Merge two DataFrames using specified join keys with different strategies (inner, left, outer, cross)
- Intelligent fuzzy merging that automatically identifies join keys using LLM analysis

**Data Organization**: Sort DataFrames by one or multiple columns with customizable ascending/descending order and optional result limiting for top-N analysis.

**Output Schema Dependencies:** Some tools produce output whose schema (e.g. which columns exist) depends on the input schema rather than being fixed. For example:
- **Filter** only removes rows — the output columns are identical to the input columns.
- **Sort** only reorders rows — the output columns are identical to the input columns.
- **Concatenate** stacks DataFrames vertically — the output columns are the union of input columns.
- **Merge** joins two DataFrames — the output columns are the combination of both input DataFrames' columns.

These tools' specifications may not clearly indicate the output schema, since their output columns are not fixed but inherited from the input data. You must infer the output schema from the input data when referencing columns in subsequent flows.

These DataFrame tools work seamlessly with the field template pattern and can be used in tool_call and map operations to build comprehensive data processing workflows.

### Control Flow Operations

#### SwitchFlow - Conditional Branching

SwitchFlow enables conditional routing in dataflows based on input data evaluation. It evaluates conditions sequentially and routes execution to the first matching case, or to the default flow if no conditions match.

<code lang="json">
{
  "type": "switch",
  "cases": [
    {
      "id": "premium_user_case",
      "conditions": {
        "type": "and", // or "or"
        "conditions": [
          {
            "operator": "scalar_equal",
            "scalar_equal": {
              "input": "scalar:user_type",
              "value": "premium"
            }
          }
        ]
      },
      "next_flow": "premium_processing_flow"
    },
    {
      "id": "high_score_case",
      "conditions": {
        "type": "and",
        "conditions": [
          {
            "operator": "scalar_greater_than",
            "scalar_greater_than": {
              "input": "scalar:score",
              "value": 80
            }
          }
        ]
      },
      "next_flow": "high_score_flow"
    },
    {
      "id": "small_dataset_case",
      "conditions": {
        "type": "and",
        "conditions": [
          {
            "operator": "dataframe_length_less_than",
            "dataframe_length_less_than": {
              "input": "dataframe:user_data",
              "value": 10
            }
          }
        ]
      },
      "next_flow": "small_dataset_flow"
    }
  ],
  "default_flow": "standard_processing_flow"
}
</code>

**Key Properties:**
- `input`: All input data sources used in the condition expressions across all cases
- `default_flow`: The flow ID to execute when no case conditions match (can be null to end execution)
- `id`: A unique identifier for each case (required for tracking and debugging)
- `next_flow`: The flow ID to execute when a specific case's conditions are met
- Cases are evaluated from top to bottom, and the first matching case is executed
- Each case can have complex conditions using "and"/"or" logic with nested condition groups

**Supported Condition Operators:**

**Scalar Value Comparisons:**
- `scalar_equal`, `scalar_not_equal`: Compare scalar values for equality
- `scalar_greater_than`, `scalar_less_than`: Numeric comparisons
- `scalar_greater_than_or_equal`, `scalar_less_than_or_equal`: Numeric comparisons with equality

**Scalar String Matching:**
- `scalar_string_contains`, `scalar_string_not_contains`: String pattern matching
- `scalar_string_starts_with`, `scalar_string_ends_with`: String prefix/suffix matching

**Scalar String Length:**
- `scalar_string_length_equal`, `scalar_string_length_not_equal`: String length equality
- `scalar_string_length_greater_than`, `scalar_string_length_less_than`: String length comparisons
- `scalar_string_length_greater_than_or_equal`, `scalar_string_length_less_than_or_equal`: String length with equality

**Series Operations:**
- `series_is_empty`, `series_is_not_empty`: Check if series is empty or not
- `series_contains`, `series_not_contains`: Check if series contains a value
- `series_length_equal`, `series_length_not_equal`: Compare series length
- `series_length_greater_than`, `series_length_less_than`: Series length comparisons
- `series_length_greater_than_or_equal`, `series_length_less_than_or_equal`: Series length with equality

**DataFrame Operations:**
- `dataframe_is_empty`, `dataframe_is_not_empty`: Check if dataframe is empty or not
- `dataframe_length_equal`, `dataframe_length_not_equal`: Compare dataframe row count
- `dataframe_length_greater_than`, `dataframe_length_less_than`: DataFrame row count comparisons
- `dataframe_length_greater_than_or_equal`, `dataframe_length_less_than_or_equal`: DataFrame row count with equality

Input: scalar, series, or dataframe values used in conditions
Output: Routes to specified flow (no direct data output)

#### ConfluenceFlow - Merging Switch Branch Outputs

ConfluenceFlow merges outputs from different switch branches that produce the same type of data through different operations and flows. This is useful when multiple switch branches generate equivalent data structures that need to be unified into a consistent format with a unified ID.

<code lang="json">
{
  "id": "confluence_flow_id",
  "description": "Merge branch outputs into unified format",
  "depends_on": ["switch_flow_id"],
  "operation": {
    "type": "confluence",
    "branch_outputs": [
      {
        "source_id": "dataframe:branch1_output",
        "rename_columns": {
          "website": "url",
          "title": "headline"
        }
      },
      {
        "source_id": "dataframe:branch2_output",
        "rename_columns": {
          "website_url": "url",
          "page_title": "headline"
        }
      }
    ]
  },
  "input": null, // No input required as they are specified in the branch_outputs
  "output": {
    "type": "dataframe",
    "id": "dataframe:unified_result"
  }
}
</code>

**IMPORTANT - Data Reference After Confluence:**

After the confluence operation, subsequent flows MUST use the unified output ID and the standardized column names:

- Use `dataframe:unified_result` to reference the merged dataframe
- Use the renamed column names (`url`, `headline`) NOT the original branch column names (`website`/`website_url`, `title`/`page_title`)

**Key Properties:**
- `depends_on`: MUST contain exactly one element - the ID of the SwitchFlow that produces the branch outputs
- `branch_outputs`: Array of branch output mappings defined in the operation
- `source_id`: The output ID from each branch to merge
- `rename_columns`: Column mapping for dataframes (optional for scalar/series)
- Output `id`: Directly represents the unified ID that subsequent flows should use

**Output Types:**
- `scalar`: Merges scalar outputs (no column mapping needed)
- `series`: Merges series outputs (no column mapping needed)
- `dataframe`: Merges dataframe outputs with optional column renaming

**Usage Pattern:**
1. Switch branches produce equivalent data through different operations
2. Each branch outputs data with potentially different column names/structure
3. Confluence operation defines how to merge and normalize the branch outputs
4. Output ID becomes the unified ID for subsequent flows

**Important Notes:**
- **REQUIRED**: ConfluenceFlow MUST depend on exactly one SwitchFlow via `depends_on` field
- All branch outputs must be of the same data type (all scalars, all series, or all dataframes)
- For dataframes, `rename_columns` allows standardizing column names across branches
- The output ID directly becomes the unified identifier for subsequent flows
- Switch branches outside the confluence should not reference individual branch IDs

Input: Outputs from multiple switch branches
Output: Standard output types (DataframeOutput, SeriesOutput, or ScalarOutput)

#### LoopFlow - Iterative Processing

LoopFlow enables iterative processing in dataflows using three different loop types: While, ForEach, and Repeat. Each loop type executes a body of flows repeatedly based on different conditions.

**CRITICAL WARNING**: Each loop type has its own specific structure and properties. DO NOT mix structures between different loop types:
- While loops use `variables` and `updates` for variable management
- ForEach loops use `input` (series only) and `element_id`
- Repeat loops use `max_iterations`
- Using While loop's `updates` in ForEach loops is INCORRECT and will cause errors!

**While Loop - Condition-based iteration with variable management:**

<code lang="json">
{
  "id": "while_loop_flow",
  "description": "While loop with variable management",
  "depends_on": [],
  "operation": {
    "type": "while",
    "variables": {
      "variable:scalar:current_page": {
        "type": "scalar",
        "initial_value": 1
      },
      "variable:scalar:total_processed": {
        "type": "scalar",
        "initial_value": 0
      },
      "variable:scalar:error_count": {
        "type": "scalar",
        "initial_value": 0
      },
      "variable:dataframe:accumulated_data": {
        "type": "dataframe",
        "initial_value": []
      },
      "variable:series:error_list": {
        "type": "series",
        "initial_value": []
      }
    },
    "conditions": {
      "type": "and",
      "conditions": [
        {
          "operator": "scalar_less_than",
          "scalar_less_than": {
            "input": "scalar:current_page",
            "value": "variable:scalar:max_pages"
          }
        }
      ]
    },
    "updates": {
      "variable:scalar:current_page": {
        "operation": "increment",
        "value": 1
      },
      "variable:scalar:total_processed": {
        "operation": "increment_by_dataframe_length",
        "dataframe_id": "dataframe:page_data"
      },
      "variable:scalar:error_count": {
        "operation": "increment_by_series_length",
        "series_id": "series:current_errors"
      },
      "variable:dataframe:accumulated_data": {
        "operation": "append_rows",
        "dataframe_id": "dataframe:page_data"
      },
      "variable:series:error_list": {
        "operation": "append_elements",
        "series_id": "series:current_errors"
      }
    }
  },
  "body": {
    "begin": "fetch_page_flow",
    "end": "process_results_flow"
  },
  "input": "variable:scalar:max_pages",
  "output": {
    "type": "dataframe",
    "id": "dataframe:all_pages_data"
  }
}
</code>

**While Loop Variable Management:**

- **variables**: Optional dictionary defining loop variables with their types and initial values:
  - `type`: "variable:scalar:", "variable:series:", or "variable:dataframe:"
  - `initial_value`: Initial value for the variable ([] for series and dataframes, specific values for scalars)

- **updates**: Optional dictionary defining how variables are updated after each iteration:
  - `increment`: Add a numeric value (int or float) to scalar variables
  - `increment_by_dataframe_length`: Add the length of a dataframe to scalar variables
  - `increment_by_series_length`: Add the length of a series to scalar variables
  - `append_rows`: Append rows from source dataframe to target dataframe
  - `append_elements`: Append elements from source series to target series

**CRITICAL**: All variables referenced in `updates` MUST be defined in the `variables` section first. You cannot update a variable that hasn't been declared in while loop `variables`.

**IMPORTANT**: For `increment` operations, the `value` must be a literal number (int or float), not a variable reference. For `increment_by_dataframe_length`, use `dataframe_id` to specify the dataframe. For `increment_by_series_length`, use `series_id` to specify the series.

**ForEach Loop - Series iteration:**

<code lang="json">
{
  "id": "foreach_loop_flow",
  "description": "ForEach loop for series iteration",
  "depends_on": [],
  "operation": {
    "type": "for_each",
    "input": "series:items_to_process",
    "element_id": "variable:scalar:current_item"
  },
  "body": {
    "begin": "process_item_flow",
    "end": "save_result_flow"
  },
  "input": "series:items_to_process",
  "output": {
    "type": "dataframe",
    "id": "dataframe:processed_items"
  }
}
</code>

In ForEach loops, each element from the input series becomes available as a scalar variable with the specified `element_id`. The loop body can reference this scalar (e.g., `variable:scalar:current_item`) instead of the original series collection.

**IMPORTANT**: ForEach loops do NOT support `variables` or `updates` properties - these are exclusive to While loops only!

**Repeat Loop - Fixed iteration count:**

<code lang="json">
{
  "id": "repeat_loop_flow",
  "description": "Repeat loop with fixed iterations",
  "depends_on": [],
  "operation": {
    "type": "repeat",
    "max_iterations": 5
  },
  "body": {
    "begin": "generate_sample_flow",
    "end": "collect_sample_flow"
  },
  "input": null,
  "output": {
    "type": "series",
    "id": "series:collected_samples"
  }
}
</code>

**IMPORTANT**: Repeat loops do NOT support `variables`, `updates`, or `conditions` properties - they only use `max_iterations` for simple counting!

**Key Properties:**

- **operation**: Contains the specific loop type and its configuration:
  - For while loops: `condition` (same operators as SwitchFlow), optional `input` (data sources used in conditions), optional `variables` (variable initialization), and optional `updates` (variable update operations)
  - For for_each loops: `input` (the series being iterated over - only series type allowed) and `element_id` (the scalar variable name for each iteration element) - NO variables or updates allowed
  - For repeat loops: `max_iterations` (fixed number of iterations, no input needed) - NO variables, updates, or conditions allowed

**IMPORTANT**: Each loop type has exclusive properties. Never use while loop properties (`variables`, `updates`) in for_each or repeat loops!

- **body**: Defines the loop body execution:
  - `begin`: The flow ID of the first flow in the loop body
  - `end`: The flow ID of the last flow in the loop body

- **output**: The accumulated data from the loop body after all iterations complete. Can only be DataframeOutput or SeriesOutput (ScalarOutput not supported for loops)

**Loop Execution:**
1. The loop evaluates its condition (while) or iteration count (repeat/for_each)
2. If condition is met, executes flows from `begin` to `end`
3. Repeats until condition is false or all iterations complete
4. Returns accumulated output from all iterations

Input: Varies by loop type (scalar/series/dataframe for while, series for for_each, none for repeat)
Output: SeriesOutput or DataframeOutput only (accumulated data from loop body iterations)

#### HumanInteractionFlow - Human-in-the-Loop Interaction

HumanInteractionFlow enables interactive workflows that pause execution to gather input, confirmation, or choices from users. This flow type supports three interaction types: approval prompts, data input requests, and multiple-choice selections.

**IMPORTANT**: Only use human interaction when explicitly requested by users or when the workflow genuinely requires human input to proceed effectively.

**Approval Interaction - Simple confirmation request:**

<code lang="json">
{
  "id": "approval_flow",
  "description": "Request user approval before proceeding",
  "depends_on": [],
  "operation": {
    "type": "human_interaction",
    "interaction": {
      "type": "approval",
      "prompt": "Confirm sending email?"
    },
    "timeout_seconds": 180
  }
}
</code>

**IMPORTANT - Approval Flow Behavior:**

When you use an approval interaction, the system runtime will automatically:
1. Pause execution and wait for user input (approve/reject)
2. If user approves, continue with the next flow in the sequence
3. If user rejects, the workflow terminates

**No additional switch logic is needed** to handle the approval response. The runtime system automatically routes execution based on the user's choice without requiring a SwitchFlow operation.

**Data Input Interaction - Collect user-provided values:**

**CRITICAL**: All `user_input` values MUST be scalar variables only. Series and DataFrame variables are NOT supported.

<code lang="json">
{
  "id": "data_input_flow",
  "description": "Collect multiple user inputs for processing",
  "depends_on": [],
  "operation": {
    "type": "human_interaction",
    "interaction": {
      "type": "data_input",
      "prompt": "Please provide the following information:",
      "user_input": [
        {
          "name": "variable:scalar:company_name",
          "description": "What is the company name?"
        },
        {
          "name": "variable:scalar:industry",
          "description": "Which industry does the company operate in?"
        }
      ]
    },
    "timeout_seconds": 180
  }
}
</code>

**Multiple Choice Interaction - Select from predefined options:**

**CRITICAL**: The `name` in `choices` MUST be a scalar variable only. Series and DataFrame variables are NOT supported.

<code lang="json">
{
  "id": "choice_flow",
  "description": "User selects one option from predefined choices",
  "depends_on": [],
  "operation": {
    "type": "human_interaction",
    "interaction": {
      "type": "multiple_choice",
      "prompt": "Select your preferred analysis type:",
      "choices": {
        "name": "variable:scalar:analysis_type",
        "values": ["Basic Analysis", "Detailed Report", "Executive Summary"]
      }
    },
    "timeout_seconds": 180
  }
}
</code>

**Key Properties:**

- **operation.type**: Always "human_interaction"
- **interaction.type**: One of "approval", "data_input", or "multiple_choice"
- **interaction.prompt**: Clear, friendly question or instruction for the user
- **timeout_seconds**: Optional timeout in seconds (default: 180)

**Interaction Types:**

1. **approval**: Simple yes/no confirmation
   - User responds with approval or rejection
   - Used for critical operations requiring confirmation

2. **data_input**: Collect one or multiple text values
   - `user_input`: Array of objects with `name` and `description`
   - Each item requests a specific piece of information
   - Returns structured data with all user inputs

3. **multiple_choice**: Select from predefined options
   - `choices`: Object with `name`, `prompt`, and `values` array
   - User selects one option from the list
   - Returns the selected value

**Result Storage**: User inputs and selections are stored as variables accessible in subsequent flows

**Best Practices:**

- Use approval for irreversible or critical operations
- Use data_input when you need specific information to proceed
- Use multiple_choice when you want to guide users through predefined options
- Keep prompts concise and clear
- Set appropriate timeouts (default 180 seconds)
- Only use when workflow genuinely needs human input
- Avoid excessive human interaction that could interrupt workflow automation

### Argument Types

For tool arguments in dataflows, use these type specifications:

#### 1. Predefined Arguments

Static values determined at design time:

<code lang="json">
{
  "name": "pages",
  "type": "predefined",
  "value": 10,
  "description": "concise_and_friendly_question"
}
</code>

Generate a concise, friendly, and natural question to help users understand the predefined parameter. For example: for the `sheet_id` parameter, the question would be: "Which sheet would you like to read?"

**Arguments with Variable References:**

Arguments can reference dataflow variables using `variable:scalar|series|dataframe:variable_name` syntax:

<code lang="json">
{
  "name": "location",
  "type": "predefined",
  "value": "variable:scalar:target_city",
  "description": "concise_and_friendly_question"
}
</code>

To reference the variable's value as a formatted string in predefined arguments, use the `${variable:scalar|series|dataframe:variable_name}` syntax.

**Arguments with Output References:**

Arguments can reference previous output using `dataframe|series|scalar:variable_name` syntax:

<code lang="json">
{
  "name": "queries",
  "type": "from_output",
  "value": "dataframe:generated_queries" // Formatted string reference `${scalar|series|dataframe:variable_name}` is not allowed in from_output values.
  // No description needed in this case
}
</code>

Where `generated_queries` is some output in previous flows.

##### WARNING

You should directly use variables, flow outputs, etc. as arguments (see Arguments section) to call tool_call operations. Do not use LLM calls to extract parameters when the arguments are directly available.

#### 2. Map Item Arguments

Values extracted from the data being processed in map operations:

<code lang="json">
{
  "name": "query",
  "type": "map_item",
  "value": "dataframe:twitter_keywords.keyword"
}
</code>

##### WARNING

A tool's argument list can have at most one `map_item`. This indicates that the tool will map over the values of this specific parameter. A tool's argument list cannot contain two or more `map_item` arguments.

#### Argument Examples

**Basic Tool Call with Predefined Arguments:**

<code lang="json">
{
  "type": "tool_call",
  "tool": {
    "id": "search_something_interest",
    "arguments": [
      {
        "name": "queries",
        "type": "from_output",
        "value": "series:keywords"
      },
      {
        "name": "count",
        "type": "predefined",
        "value": 20,
        "description": "How many results would you like to retrieve?"
      }
    ]
  }
}
</code>

**Map Operation with Mixed Arguments:**

<code lang="json">
{
  "type": "map",
  "tool": {
    "id": "perform_some_search",
    "arguments": [
      {
        "name": "query",
        "type": "map_item",
        "value": "dataframe:keywords.keyword"
      },
      {
        "name": "pages",
        "type": "predefined",
        "value": 5,
        "description": "How many pages would you like to search?"
      },
      {
        "name": "lang",
        "type": "predefined",
        "value": "en",
        "description": "Which language would you like to search in?"
      }
    ]
  }
}
</code>

**Arguments with Prefixes:**

When arguments have prefixes (such as requestBody__), do not omit the prefix in the argument name:
<code lang="json">
{
  "name": "requestBody__data",
  ...
}
</code>

The prefix is part of the tool's expected parameter name and must be preserved exactly as defined in the tool specification.

### Variable Management

Variables are configuration properties of the dataflow, defined once and used throughout. Variables can now include literal data creation as well as static configuration values.

#### Variable Definition

Variables now support data type prefixes (scalar:, series:, dataframe:) in their names and can contain both configuration values and literal data:

<code lang="json">
{
  "variables": [
    {
      "name": "variable:scalar:target_language",
      "default_value": "zh",
      "description": "Which language to search in?"
    },
    {
      "name": "variable:scalar:search_depth",
      "default_value": 10,
      "description": "How many pages to search?"
    },
    {
      "name": "variable:series:search_keywords",
      "default_value": ["AI", "machine learning", "data science"],
      "description": "What keywords would you like to search for?"
    },
    {
      "name": "variable:dataframe:sample_data",
      "default_value": [
        {"name": "Alice", "age": 30, "city": "New York"},
        {"name": "Bob", "age": 25, "city": "London"}
      ],
      "description": "What sample data would you like to use?"
    }
  ]
}
</code>

#### When to Use Literal Data Variables

- Initial seed data from user input
- Known configuration lists
- Static reference data
- Test data or examples
- Converting user-provided context into structured format

#### Variable vs Arguments Distinction

- **Variables**: Static dataflow configuration and literal data (e.g., language, depth, location, seed data)
- **Arguments**: Dynamic tool parameters that can reference variables or data

##### Using Variables in Arguments

Variables can be referenced in predefined, from_output and map_item arguments:

<code lang="json">
{
  "name": "lang",
  "type": "predefined",
  "value": "variable:scalar:target_language",
  "description": "Which language to search in?"
}
</code>

#### Best Practices

- Use data type prefixes in variable names `variable:scalar|series|dataframe`, always include the `variable:` prefix when referencing variables
- Keep variables minimal and focused on truly configurable aspects
- ONLY use `variable:scalar:` variables in title, objective and flow descriptions
- Never reference `variable:series:` or `variable:dataframe:` variables in title, objective, or flow descriptions
- Provide clear, friendly descriptions for each variable
- Default values should match typical user intent

### JSON Schema to DataFrame Conversion

MCP tools have input/output defined in JSON schema format, but dataflows operate on Series and DataFrame structures. JSON outputs are automatically flattened into DataFrame columns:

**JSON Output Example:**

<code lang="json">
{
  "status": "success",
  "results": [
    {"title": "Article 1", "url": "https://example1.com"},
    {"title": "Article 2", "url": "https://example2.com"}
  ]
}
</code>

**Flattened DataFrame Columns:**

- `status` - contains "success"
- `results.title` - contains article titles
- `results.url` - contains article URLs

### Column Reference Syntax

When referencing columns:

- `series:series_name` - entire series as input
- `dataframe:table_name.column_name` - specific column from a dataframe
- `dataframe:table_name.nested.parent.child.column_name` - nested JSON fields using dot notation
- `variable:series:series_name` - entire series as input from variable
- `variable:dataframe:table_name.column_name` - specific column from a dataframe from variable
- `variable:dataframe:table_name.nested.parent.child.column_name` - nested JSON fields using dot notation from variable

### Flow Dependencies

Dataflows support explicit dependencies through the `depends_on` field:

- Each flow can explicitly list other flow IDs it depends on using the `depends_on` field
- Dependencies are defined as a list of flow IDs that must complete before this flow executes
- This complements data flow dependencies (based on input/output) with explicit control flow dependencies
- The system uses both explicit dependencies and data dependencies to determine execution order

### Flow Design Patterns & Best Practices

#### Core Pattern: Field Template Pattern - Structured Data Building

**This is the fundamental pattern that underlies all dataflow operations and should be your primary approach for building result sheets systematically:**

Initial Data → DataFrame
Map (fill field 1) → DataFrame with field 1 populated
Map (fill field 2) → DataFrame with fields 1 & 2 populated
Map (fill field 3) → DataFrame with fields 1, 2 & 3 populated
...

**Key principles:**
- Each map operation focuses on filling one specific field/column
- Use relevant tools from `AI Field Template` MCP and other tools
- Build data incrementally, column by column, row by row
- Never attempt to generate multiple fields in a single LLM call
- Leverage `AI Field Template` MCP tools for structured data transformation

**Use this pattern for:**
- Transforming text into structured data
- Transformations on column data
- Extracting structured data from text
- Formatting text data into structured format

**Implementation:** Use the relevant tools in the `AI Field Template` MCP in combination with map operations following the field template pattern.

### Common Dataflow Patterns

#### Pattern 1: Data Collection & Processing

Tool Call (collect data) → DataFrame
Map (enrich/process each item using field template) → Enhanced DataFrame
Apply (analyze/summarize) → Final Result

**Core approach:** Use field template pattern in the Map step to systematically populate each field of the result structure.

#### Pattern 2: Multi-source Data Integration

Tool Call A → DataFrame A
Tool Call B → DataFrame B
Map (merge/enrich using field template) → Integrated DataFrame
Apply (analyze/compare) → Combined Analysis

**Core approach:** Use field template pattern to systematically combine and structure data from multiple sources.

#### Pattern 3: Iterative Data Building

Tool Call (get initial data) → Series/DataFrame
Map (detailed processing using field template) → Enhanced DataFrame
Map (final enrichment using field template) → Complete DataFrame
Apply (summarize) → Final Report

**Core approach:** Use field template pattern throughout the iterative process to build the final structured result incrementally.

When users request to export or save data to other locations, clearly understand their intent, analyze which related data they want and which dataframes the data ultimately join together, and select the relevant key result dataframes in the flow process for saving.

### Best Practices

#### Field Template Pattern - Core Approach
1. **Field Template Pattern**: Build data systematically using map operations to fill each column individually - this is the fundamental approach for all structured data creation
2. **Column-by-Column Construction**: Use map operations to build data column by column; never generate multiple fields in single operations
3. **Structured Data Building**: Transform unstructured text into structured data by filling each field template with appropriate tools and map operations

#### Dataflow Efficiency Principles
1. **Batch Operations**: Use map operations instead of multiple individual tool calls
2. **Pipeline Optimization**: Chain operations efficiently to minimize data copying
3. **Parallel Execution**: Map operations can be parallelized for better performance
4. **Memory Efficiency**: Process data in chunks when dealing with large datasets

#### Error Handling and Robustness
- Use appropriate data types to ensure type safety
- Design flows to be resilient to partial failures in map operations
- Provide meaningful descriptions for each flow to aid debugging

#### General Best Practices
1. **Minimize Data Transfers**: Design flows to process data efficiently without unnecessary copying
2. **Clear Naming**: Use descriptive names for intermediate data objects
3. **Appropriate Granularity**: Balance between too many small flows and overly complex single flows
4. **Type Consistency**: Ensure data type compatibility between flows
5. **Scalability**: Design with large datasets in mind, using streaming where appropriate
6. **Avoid Complex Nested Conditions**: Unless absolutely necessary and explicitly required by users, avoid creating complex multi-level nested IF conditions in SwitchFlow operations - prefer simpler, flatter conditional structures for better maintainability and readability

### Case Study: AI News Analysis

Complete workflow demonstrating the field template pattern:

Tool Call (hao123_search_ai_agent) → dataframe:info [url, headline]
Save raw search result (dataframe:info) to Google Sheet
Map (dataframe:info.url, crawler_tool) → dataframe:crawl_result [url, body]
Map (dataframe:crawl_result.body, extract_topic_field_template) → series:topic [LLM, Memory, ...]
Map (dataframe:crawl_result.body, extract_views_field_template) → series:views [23, 444, 23, ...]
Map (series:views, tag_quality_field_template) → series:quality [high, low, ...]
Map (dataframe:crawl_result.body, sentiment_analysis_field_template) → series:sentiment [+, -, neutral]
Save field template result (dataframe:final_analysis) to Google Sheet

Implementation breakdown:

1. **Initial data collection**: Search for AI-related news articles
2. **Content extraction**: Crawl each URL to get full article content
3. **Field template enrichment**: Systematically extract structured data:
   - Topic classification from article body
   - View count extraction from article content
   - Quality assessment based on view metrics
   - Sentiment analysis of article content
4. **Result building**: Each map operation adds one column to build the complete analysis sheet
5. **Data export**: Save raw search results and final field template results to Google Sheets for further use

**Key benefits of this approach:**
- Each field is extracted independently and reliably without overwhelming LLM context limits
- Easy to modify or extend with additional fields
- Clear separation of concerns for each data extraction task
- Scalable to hundreds or thousands of articles
- Maintains data integrity throughout the pipeline
