---
name: query-writing
description: For writing and executing SQL queries — from simple single-table queries to complex multi-table JOINs and aggregations on PostgreSQL databases
---

# Query Writing Skill

## When to Use This Skill

Use this skill when you need to answer a question by writing and executing a SQL query.

## Workflow for Simple Queries

For straightforward questions about a single table:

1. **Identify the table** — Which table has the data?
2. **Get the schema** — Use `get_schema` to see columns
3. **Write the query** — SELECT relevant columns with WHERE/LIMIT/ORDER BY
4. **Execute** — Run with `execute_query`. If it errors, read the message, fix the SQL, and retry.
5. **Format answer** — Present results clearly in Portuguese

## Workflow for Complex Queries

For questions requiring multiple tables:

### 1. Plan Your Approach
Break down the task:
- Identify all tables needed
- Map relationships (foreign keys or common columns)
- Plan JOIN structure
- Determine aggregations

### 2. Examine Schemas
Use `get_schema` for EACH table to find join columns and needed fields.

### 3. Construct Query
- SELECT — Columns and aggregates
- FROM/JOIN — Connect tables on matching columns
- WHERE — Filters before aggregation
- GROUP BY — All non-aggregate columns
- HAVING — Filters after aggregation
- ORDER BY — Sort meaningfully
- LIMIT — Default 20 rows

### 4. Execute
Run with `execute_query`. If it returns an error, read the message, correct the
SQL, and retry — there is no separate validation step.

## PostgreSQL-Specific Notes

### Identifiers
- Default schema is `public`. Qualify only when needed: `"public"."vendas"`.
- Unquoted identifiers are folded to lowercase. Use double quotes whenever
  the name has uppercase, spaces, special chars, or is a reserved word:
  `"Table_Name"."Column Name"`. Excel uploads sanitize names to lowercase
  with underscores, so quoting is usually optional but still safe.
- Single quotes are for string literals only — never for identifiers.

### Strings, casts and math
- String concatenation: `||` (e.g. `first || ' ' || last`).
- Case-insensitive search: `ILIKE` (`coluna ILIKE '%termo%'`) or
  `lower(coluna) = lower('termo')`.
- Casts: `value::numeric`, `value::int`, `value::date`. For decimal
  division use `(num::numeric / denom::numeric)`.
- `ROUND(value, 2)` requires a `numeric` argument: `ROUND(x::numeric, 2)`.
- Number formatting: `to_char(value, 'FM999G999G990D00')` (Brazilian
  thousands `.` and decimals `,` are controlled by `lc_numeric`; for
  guaranteed pt-BR output use `to_char(value, 'FM999G999G990D00', 'NLS_NUMERIC_CHARACTERS='',.''')`).

### Dates and time
- Today / now: `current_date`, `now()`, `current_timestamp`.
- Truncation: `date_trunc('month', col)`, `date_trunc('day', col)`.
- Extraction: `extract(year from col)`, `extract(month from col)`.
- Intervals: `col >= now() - interval '30 days'`.
- Formatting: `to_char(col, 'DD/MM/YYYY')`.

### Joins and set ops
- `FULL OUTER JOIN` is supported natively (no UNION trick needed).
- `LATERAL` joins are available for correlated subqueries.

### Aggregation and grouping
- String aggregation: `STRING_AGG(coluna, ', ' ORDER BY coluna)`.
- Array aggregation: `ARRAY_AGG(coluna)`.
- `DISTINCT ON (col)` selects the first row per group ordered by something.
- `FILTER (WHERE ...)` for conditional aggregates: `COUNT(*) FILTER (WHERE status = 'ok')`.

### Nulls
- `COALESCE(a, b, c)` for first non-null.
- `NULLIF(a, b)` returns null when `a = b` — useful before division to
  avoid divide-by-zero: `a / NULLIF(b, 0)`.

### CTEs and window functions
- Always available: use `WITH ... AS ( ... )` for readability.
- Window functions (`ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)`,
  `RANK()`, `LAG()`, `LEAD()`, `SUM() OVER (...)`) are first-class.

### JSON
- Stored as `json` or `jsonb` (prefer `jsonb` for indexed access).
- Operators: `col->'key'` (json), `col->>'key'` (text), `col @> '{"k":1}'`
  (contains), `jsonb_array_elements(col)` to expand arrays.

## Quality Guidelines

- Query only relevant columns (not SELECT *)
- Always apply LIMIT (20 default)
- Use table aliases for clarity
- For complex queries: plan before executing
- Never use DML statements (INSERT, UPDATE, DELETE, DROP)
- Always respond in Portuguese (Brazil)
- Include insights about the data patterns
