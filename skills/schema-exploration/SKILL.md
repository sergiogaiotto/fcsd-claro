---
name: schema-exploration
description: For discovering and understanding database structure, tables, columns, relationships, and data content
---

# Schema Exploration Skill

## When to Use This Skill

Use this skill when you need to:
- Understand the database structure
- Find which tables contain certain types of data
- Discover column names and data types
- Map relationships between tables
- Answer questions like "Quais tabelas existem?" or "Quais colunas tem a tabela X?"

## Workflow

### 1. List All Tables
Use `list_tables` tool to see all available tables in the database.
Returns table names, column info, and row counts.

### 2. Get Schema for Specific Tables
Use `get_schema` tool with table names to examine:
- **Column names** — What fields are available
- **Data types** — Common PostgreSQL types you will see:
  - **Numeric**: `integer` / `int4`, `bigint` / `int8`, `numeric(p,s)`,
    `real` / `float4`, `double precision` / `float8`
  - **Text**: `text`, `varchar(n)`, `character varying`
  - **Boolean**: `boolean`
  - **Date/time**: `date`, `timestamp`, `timestamptz`, `time`, `interval`
  - **Semi-structured**: `json`, `jsonb`, `uuid`, `bytea`
  - **Arrays**: any type can be an array, e.g. `text[]`, `integer[]`
- **Sample data** — Example rows to understand content
- **Row count** — Total records

### 3. Map Relationships
Identify how tables connect:
- Foreign keys are explicit in PostgreSQL — when present, prefer them
  over guessing. They show up in `information_schema.table_constraints`
  and `information_schema.referential_constraints` (the `get_schema`
  tool surfaces them when available).
- When no FK is declared, look for columns with similar names across
  tables (`*_id`, name matches).
- Document parent-child relationships, including the join cardinality
  (1:N, N:M with a junction table).

### 4. Answer the Question
Provide clear information in Portuguese about:
- Available tables and their purpose
- Column names and what they contain
- How tables relate to each other
- Sample data to illustrate content

## Response Format

**For "listar tabelas" questions:**
- Show all table names with brief descriptions
- Include row counts
- Group related tables when possible

**For "descrever tabela" questions:**
- List all columns with data types
- Explain what each column likely contains
- Show sample data for context
- Note potential relationships to other tables

**For "como consultar X" questions:**
- Identify required tables
- Map the JOIN path
- Explain the relationship chain
- Suggest the query-writing skill for execution

## Tips

- Column names from Excel uploads are sanitized (lowercase, underscores)
- Table names come from Excel sheet names (also sanitized)
- All user data lives in the `public` schema by default — don't qualify
  unless you actually have multiple schemas
- PostgreSQL folds unquoted identifiers to lowercase. If a name has
  uppercase or spaces, quote it with double quotes (`"Minha Tabela"`)
- For schema introspection beyond `get_schema`, you can query
  `information_schema.tables`, `information_schema.columns`, and
  `pg_catalog.pg_indexes` — use these only when the toolkit lacks the
  detail you need
- When unsure which table to use, list all tables first
- Always respond in Portuguese (Brazil)
