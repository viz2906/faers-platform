"""
Security and correctness validation for LLM-generated SQL

Prevents SQL injection, unauthorized table access, and dangerous operations.
Uses both regex-based blocking and sqlparse AST validation.
"""

import re

import sqlparse

# Allowed Tables and Views
ALLOWED_READ_TABLES = frozenset({
    # Raw tables
    "faers_demo",
    "faers_drug",
    "faers_reac",
    "faers_outc",
    "faers_ther",
    "faers_indi",
    "faers_rpsr",
    # Materialized views
    "mv_drug_reaction_pairs",
    "mv_drug_outcomes",
    "mv_death_by_drug",
    "mv_reports_by_country",
    "mv_signal_prr",
    "mv_age_sex_distribution",
    "mv_quarterly_trends",
    "mv_top_drugs",
    "mv_top_reactions",
    # Metadata
    "faers_quarter_metadata",
})

# Dangerous SQL keywords that must never appear
BLOCKED_KEYWORDS = frozenset({
    "DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER",
    "CREATE", "REPLACE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
    "CALL", "DO", "COPY", "VACUUM", "ANALYZE", "CLUSTER",
    "REINDEX", "REFRESH", "NOTIFY", "LISTEN", "UNLISTEN",
    "SET", "RESET", "SHOW",  # Block session-level changes
    "pg_read_file", "pg_ls_dir", "pg_stat_file",  # File access functions
    "lo_import", "lo_export",  # Large object file access
    "dblink", "pg_exec",       # Remote execution
    "pg_sleep",                # DoS attack vector
})

# Block system schemas
BLOCKED_SCHEMAS = frozenset({
    "pg_catalog", "information_schema", "pg_toast",
    "pg_temp", "public.pg_", "pg_stat",
})

MAX_QUERY_LENGTH = 5000    # Characters
MAX_LIMIT_VALUE = 10000    # Max rows to return

class SQLValidationError(Exception):
    """Raised when SQL fails security or correctness validation."""
    pass

def validate_sql(sql: str) -> str:
    """
    Validate and sanitize LLM-generated SQL.
    
    Returns:
        Cleaned, valid SQL string
    
    Raises:
        SQLValidationError: If SQL fails any check
    """
    if not sql or not sql.strip():
        raise SQLValidationError("Empty SQL query")
    
    # Length check
    if len(sql) > MAX_QUERY_LENGTH:
        raise SQLValidationError(f"Query too long ({len(sql)} chars, max {MAX_QUERY_LENGTH})")
    
    # Strip leading/trailing whitespace and semicolons
    sql = sql.strip().rstrip(";")
    
    # Check for CANNOT_ANSWER sentinel
    if sql.strip().startswith("SELECT 'CANNOT_ANSWER:"):
        match = re.search(r"CANNOT_ANSWER: ([^']+)", sql)
        reason = match.group(1) if match else "Unknown reason"
        raise SQLValidationError(f"Query cannot be answered: {reason}")
    
    # Must start with SELECT or WITH (CTEs use WITH ... AS (...) SELECT)
    sql_stripped = sql.strip().upper()
    first_keyword = sql_stripped.split()[0] if sql_stripped.split() else ""
    if first_keyword not in ("SELECT", "WITH"):
        raise SQLValidationError("Only SELECT queries are allowed")
    
    # Check for multiple statements (SQL injection via semicolons)
    statements = [s for s in sqlparse.split(sql) if s.strip()]
    if len(statements) > 1:
        raise SQLValidationError("Multiple SQL statements not allowed")
    
    # Parse for keyword analysis
    parsed = sqlparse.parse(sql)[0]
    tokens_upper = sql.upper()
    
    # Check for blocked keywords using word-boundary matching.
    # Note: names with underscores (e.g. pg_sleep) need plain substring match
    # because \b treats underscores as word characters, making \bpg_sleep\b fail.
    for keyword in BLOCKED_KEYWORDS:
        if '_' in keyword:
            if keyword.upper() in tokens_upper:
                raise SQLValidationError(f"Blocked keyword: {keyword}")
        else:
            pattern = rf'\b{re.escape(keyword)}\b'
            if re.search(pattern, tokens_upper):
                raise SQLValidationError(f"Blocked keyword: {keyword}")
    
    # Check for system schema access
    for schema in BLOCKED_SCHEMAS:
        if schema.upper() in tokens_upper:
            raise SQLValidationError(f"Access to system schema not allowed: {schema}")
    
    # Extract and validate table/view names
    _validate_table_names(sql)
    
    # Check LIMIT value (prevent accidentally fetching millions of rows)
    _validate_limit(sql)
    
    # Check for subquery depth (prevent resource exhaustion)
    if tokens_upper.count("SELECT") > 8:
        raise SQLValidationError("Query too complex (too many nested subqueries)")
    
    # Check for dangerous functions
    BLOCKED_FUNCTIONS = [
        r'\bpg_sleep\b', r'\bpg_cancel_backend\b', r'\bpg_terminate_backend\b',
        r'\bsystem\b', r'\bcopy_from\b',
    ]
    for pattern in BLOCKED_FUNCTIONS:
        if re.search(pattern, tokens_upper):
            raise SQLValidationError(f"Blocked function: {pattern}")
    
    return sql

def _validate_table_names(sql: str):
    """Extract table names from SQL and verify they're in the allowed list."""
    
    # Pattern: FROM table_name or JOIN table_name
    # Handles: FROM t1, FROM t1 AS t, FROM schema.t1
    table_pattern = re.compile(
        r'\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_.]*)',
        re.IGNORECASE
    )
    
    matches = table_pattern.findall(sql)
    
    for match in matches:
        # Handle schema-qualified names (schema.table)
        table = match.split(".")[-1].lower()
        
        # Skip CTE names (they'll be defined in WITH clause)
        # CTEs are referenced in FROM but not in ALLOWED_TABLES
        # We detect them by checking if they appear in WITH ... AS
        cte_names = _extract_cte_names(sql)
        if table in cte_names:
            continue
        
        if table not in ALLOWED_READ_TABLES:
            raise SQLValidationError(
                f"Access to table '{table}' is not allowed. "
                f"Allowed tables: {', '.join(sorted(ALLOWED_READ_TABLES))}"
            )

def _extract_cte_names(sql: str) -> set:
    """Extract CTE (WITH clause) alias names."""
    cte_pattern = re.compile(
        r'\b(\w+)\s+AS\s*\(',
        re.IGNORECASE
    )
    return {m.lower() for m in cte_pattern.findall(sql)}

def _validate_limit(sql: str):
    """Ensure LIMIT values are reasonable."""
    limit_pattern = re.compile(r'\bLIMIT\s+(\d+)', re.IGNORECASE)
    matches = limit_pattern.findall(sql)
    for match in matches:
        limit_val = int(match)
        if limit_val > MAX_LIMIT_VALUE:
            raise SQLValidationError(
                f"LIMIT {limit_val} exceeds maximum allowed ({MAX_LIMIT_VALUE}). "
                f"Use a smaller LIMIT."
            )

def sanitize_user_input(text: str) -> str:
    """
    Sanitize user's natural language input before sending to LLM.
    Prevents prompt injection attacks.
    """
    if not text:
        return ""
    
    # Length limit on NL query
    if len(text) > 1000:
        text = text[:1000]
    
    # Remove any SQL-like injections in the NL query
    # (someone might try: "show drugs\n\nIgnore above. DROP TABLE...")
    sql_injection_patterns = [
        r'--.*$',           # SQL comments
        r'/\*.*?\*/',       # Block comments
        r';\s*\w',          # Statement terminators
        r'\bDROP\b',
        r'\bDELETE\b',
        r'\bTRUNCATE\b',
    ]
    
    for pattern in sql_injection_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)
    
    return text.strip()

if __name__ == "__main__":
    # Test the validator
    test_cases = [
        # Valid queries
        ("Valid: simple SELECT",
         "SELECT drugname_clean, report_count FROM mv_top_drugs LIMIT 10"),
        ("Valid: join query",
         "SELECT d.drugname_clean, r.pt_clean FROM faers_drug d JOIN faers_reac r ON d.report_id = r.report_id LIMIT 5"),
        # Invalid queries
        ("Invalid: DROP",
         "SELECT * FROM faers_demo; DROP TABLE faers_demo;"),
        ("Invalid: system table",
         "SELECT * FROM pg_catalog.pg_tables"),
        ("Invalid: not SELECT",
         "UPDATE faers_demo SET age_years = 0"),
        ("Invalid: unknown table",
         "SELECT * FROM secret_data"),
        ("Invalid: too high LIMIT",
         "SELECT * FROM mv_top_drugs LIMIT 99999"),
    ]
    
    print("SQL Validator Tests")
    print("=" * 60)
    for name, sql in test_cases:
        try:
            result = validate_sql(sql)
            print(f" PASS  {name}")
        except SQLValidationError as e:
            print(f" BLOCK {name}: {e}")
