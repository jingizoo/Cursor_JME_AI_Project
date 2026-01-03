# Dynamic Schema Configuration

## Overview

The application now includes **ALL tables dynamically** by default, making it work seamlessly with many dynamic tables. You can still limit tables/columns for performance if needed via environment variables.

## Default Behavior

- **All tables are included** in the schema sent to the LLM
- **All columns** are included (up to 50 per table by default)
- Tables explicitly mentioned in questions get **double the column limit** (100 columns)

## Environment Variables

You can configure limits via environment variables:

### `JME_MAX_TABLES`
- **Default**: `0` (unlimited - includes all tables)
- **Usage**: Set to a number to limit how many tables are included
- **Example**: `export JME_MAX_TABLES=20` to include max 20 tables

### `JME_MAX_COLS`
- **Default**: `50` columns per table
- **Usage**: Set to limit columns per table (prevents huge prompts)
- **Example**: `export JME_MAX_COLS=30` to include max 30 columns per table

## Priority Order (when `JME_MAX_TABLES` is set)

When limiting tables, the system prioritizes:

1. **Explicitly mentioned tables** - Tables whose names appear in the question
2. **Raw tables** - Most recently ingested raw tables (from `raw_sheet_registry`)
3. **Canonical tables** - Standard tables (invoices, payments, expenses, bank_txns)
4. **Other tables** - Any remaining tables

## Examples

### Include All Tables (Default)
```bash
# No environment variables needed - includes all tables
python -m uvicorn src.api:app --host 0.0.0.0 --port 8010
```

### Limit to 20 Tables for Performance
```bash
export JME_MAX_TABLES=20
export JME_MAX_COLS=30
python -m uvicorn src.api:app --host 0.0.0.0 --port 8010
```

### Include All Tables but Limit Columns
```bash
export JME_MAX_TABLES=0  # 0 = unlimited
export JME_MAX_COLS=25   # Limit to 25 columns per table
python -m uvicorn src.api:app --host 0.0.0.0 --port 8010
```

## Performance Considerations

- **More tables = larger prompts = slower LLM responses**
- If you have 100+ tables, consider setting `JME_MAX_TABLES=50` or similar
- If tables have 100+ columns, consider setting `JME_MAX_COLS=30` or similar
- Tables mentioned in questions always get priority and double column limit

## Benefits

✅ **Works with dynamic tables** - No need to manually configure which tables to include  
✅ **Automatic discovery** - All ingested tables are automatically available  
✅ **Smart prioritization** - Tables mentioned in questions are always included  
✅ **Configurable** - Can still limit for performance if needed  
✅ **Backward compatible** - Existing code works without changes



