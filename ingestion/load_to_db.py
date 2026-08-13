"""
Bulk load cleaned FAERS DataFrames into PostgreSQL

Uses PostgreSQL COPY command via psycopg2 — 50-100x faster than INSERT.
Handles schema creation, data type alignment, and materialized view refresh.
"""

import io
import json
import os
import time
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# Database Connection
def get_connection() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        database=os.getenv("POSTGRES_DB", "faers"),
        user=os.getenv("POSTGRES_USER", "faers_user"),
        password=os.getenv("POSTGRES_PASSWORD", "faers_secret_pw"),
    )
    # Disable statement timeout for ingestion — bulk COPY/DELETE on millions of rows
    # can legitimately take minutes, and the default timeout kills them prematurely.
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0;")
    conn.commit()
    return conn

# Column Mappings (DataFrame → DB column)
# Only include columns that exist in the DB schema
# Extra DataFrame columns are ignored
DB_COLUMNS = {
    "faers_demo": [
        "report_id", "caseid", "caseversion", "quarter",
        "i_f_code", "event_dt_parsed", "fda_dt_parsed",
        "rept_cod", "age_years", "sex_clean", "weight_kg",
        "age_group", "reporter_country", "occr_country", "occp_cod",
    ],
    "faers_drug": [
        "report_id", "caseid", "drug_seq", "quarter",
        "role_cod", "drug_role", "drugname", "drugname_clean",
        "prod_ai", "prod_ai_clean", "route", "route_clean",
        "dose_amt", "dose_unit", "dose_form", "dose_freq", "nda_num",
    ],
    "faers_reac": [
        "report_id", "caseid", "quarter", "pt", "pt_clean",
    ],
    "faers_outc": [
        "report_id", "caseid", "quarter", "outc_cod", "outcome_label",
    ],
    "faers_ther": [
        "report_id", "caseid", "drug_seq", "quarter",
        "start_dt_parsed", "end_dt_parsed", "dur_days",
    ],
    "faers_indi": [
        "report_id", "caseid", "drug_seq", "quarter",
        "indi_pt", "indi_pt_clean",
    ],
    "faers_rpsr": [
        "report_id", "caseid", "quarter", "rpsr_cod",
    ],
}

# Rename DF columns to match DB columns
COLUMN_RENAMES = {
    "faers_demo": {
        "event_dt_parsed": "event_dt",
        "fda_dt_parsed": "fda_dt",
        "sex_clean": "sex",
    },
    "faers_drug": {},
    "faers_reac": {},
    "faers_ther": {
        "start_dt_parsed": "start_dt",
        "end_dt_parsed": "end_dt",
    },
    "faers_indi": {},
    "faers_outc": {},
    "faers_rpsr": {},
}

# Core Bulk Loader
def bulk_load_dataframe(
    df: pd.DataFrame,
    table_name: str,
    conn: psycopg2.extensions.connection,
    on_conflict: str = "DO NOTHING",
) -> int:
    """
    Load a DataFrame into PostgreSQL using COPY for maximum speed.
    
    Returns:
        Number of rows loaded
    """
    if df is None or len(df) == 0:
        logger.warning(f"Skipping {table_name} — empty DataFrame")
        return 0
    
    # Get target DB columns
    db_cols = DB_COLUMNS.get(table_name, [])
    renames = COLUMN_RENAMES.get(table_name, {})
    
    # Rename DF columns to match DB
    df = df.rename(columns=renames)
    
    # Select only columns that exist in both DF and DB schema
    available_cols = [c for c in db_cols if c in df.columns]
    missing = [c for c in db_cols if c not in df.columns]
    
    if missing:
        logger.warning(f"  {table_name}: Missing columns (will be NULL): {missing}")
    
    df_subset = df[available_cols].copy()
    
    # SCHEMA DRIFT / JSONB ESCAPE HATCH: 
    # Capture any unexpected columns from the FDA files into the extended_attributes JSONB column
    unmapped_cols = [c for c in df.columns if c not in db_cols and c != "quarter"]
    if unmapped_cols:
        logger.info(f"  {table_name}: Capturing {len(unmapped_cols)} unmapped columns into extended_attributes JSONB: {unmapped_cols[:5]}...")
        df_subset["extended_attributes"] = df[unmapped_cols].apply(
            lambda row: json.dumps({k: v for k, v in row.items() if pd.notnull(v)}), 
            axis=1
        )
    else:
        df_subset["extended_attributes"] = "{}"
    
    available_cols.append("extended_attributes")
    
    # Replace pandas NA/NaN/NaT with None (PostgreSQL NULL)
    df_subset = df_subset.where(pd.notnull(df_subset), None)
    
    # Convert timestamps to strings for COPY
    for col in df_subset.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns:
        df_subset[col] = df_subset[col].astype(str).replace("NaT", "\\N")
    
    start = time.time()
    
    try:
        with conn.cursor() as cur:
            # Ensure no timeout kills this bulk load
            cur.execute("SET statement_timeout = 0;")
            # Write DataFrame to in-memory CSV buffer
            buffer = io.StringIO()
            df_subset.to_csv(
                buffer,
                index=False,
                header=False,
                sep="\t",
                na_rep="\\N",
                date_format="%Y-%m-%d",
            )
            buffer.seek(0)
            
            cols_str = ", ".join(available_cols)
            cur.copy_expert(
                f"""COPY {table_name} ({cols_str})
                    FROM STDIN
                    WITH (FORMAT CSV, DELIMITER '\t', NULL '\\N', QUOTE '"')
                """,
                buffer,
            )
            rows_loaded = cur.rowcount if cur.rowcount >= 0 else len(df_subset)
        
        conn.commit()
        elapsed = time.time() - start
        rate = len(df_subset) / elapsed if elapsed > 0 else 0
        logger.info(f"   {table_name}: {len(df_subset):,} rows in {elapsed:.1f}s ({rate:,.0f} rows/sec)")
        return rows_loaded
    
    except Exception as e:
        conn.rollback()
        logger.error(f"   Failed loading {table_name}: {e}")
        raise

# Pre-load checks
def ensure_schema_exists(conn: psycopg2.extensions.connection):
    """Apply schema.sql and materialized_views.sql if tables don't exist yet.
    
    Uses CREATE TABLE IF NOT EXISTS so it's safe to run on every pipeline call.
    On a fresh RDS instance this creates all tables and materialized views.
    On an existing DB it's a fast no-op.
    """
    # Check if tables already exist
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'faers_demo'
        """)
        exists = cur.fetchone()[0] > 0

    if exists:
        return  # Schema already applied — fast no-op

    logger.info("First-time setup: applying database schema...")

    # Locate SQL files relative to this file
    base = Path(__file__).parent.parent / "database"
    schema_file = base / "schema.sql"
    views_file  = base / "materialized_views.sql"

    for sql_file in [schema_file, views_file]:
        if not sql_file.exists():
            logger.warning(f"SQL file not found, skipping: {sql_file}")
            continue
        sql = sql_file.read_text(encoding="utf-8")
        try:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = 0;")
                cur.execute(sql)
            conn.commit()
            logger.info(f"Applied: {sql_file.name}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to apply {sql_file.name}: {e}")
            raise


def quarter_already_loaded(conn: psycopg2.extensions.connection, quarter: str) -> bool:
    """Check if data for this quarter already exists."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM faers_demo WHERE quarter = %s", (quarter,))
        count = cur.fetchone()[0]
    if count > 0:
        logger.warning(f"Quarter {quarter} already has {count:,} DEMO rows. Use --force to reload.")
        return True
    return False

def delete_quarter(conn: psycopg2.extensions.connection, quarter: str):
    """Remove all data for a specific quarter (for re-loading)."""
    logger.warning(f"Deleting all data for quarter {quarter}...")
    tables = ["faers_indi", "faers_ther", "faers_rpsr", "faers_outc",
              "faers_reac", "faers_drug", "faers_demo"]
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"DELETE FROM {table} WHERE quarter = %s", (quarter,))
            logger.info(f"  Deleted from {table}: {cur.rowcount} rows")
    conn.commit()

# Materialized View Refresh
MATERIALIZED_VIEWS = [
    "mv_drug_reaction_pairs",
    "mv_drug_outcomes",
    "mv_death_by_drug",
    "mv_reports_by_country",
    "mv_signal_prr",
    "mv_age_sex_distribution",
    "mv_quarterly_trends",
]

def refresh_materialized_views(conn: psycopg2.extensions.connection, status_callback=None):
    """Refresh all analytics materialized views."""
    logger.info("Refreshing materialized views...")

    with conn.cursor() as cur:
        # Disable timeout — large view refreshes can take minutes
        cur.execute("SET statement_timeout = 0;")

        for i, view in enumerate(MATERIALIZED_VIEWS):
            if status_callback:
                progress = int(80 + (i / len(MATERIALIZED_VIEWS)) * 20)
                status_callback("Views", f"Refreshing {view}...", progress)

            start = time.time()
            try:
                # Use non-concurrent refresh — avoids unique index requirements
                # and is simpler/more reliable than CONCURRENTLY
                cur.execute(f"REFRESH MATERIALIZED VIEW {view}")
                conn.commit()
                elapsed = time.time() - start
                logger.info(f"   {view}: refreshed in {elapsed:.1f}s")
            except Exception as e:
                conn.rollback()
                logger.error(f"   {view}: failed — {e}")

# Full Quarter Load Orchestration
def load_quarter(
    tables: dict,
    quarter: str,
    force: bool = False,
    skip_views: bool = False,
    status_callback = None,
) -> dict:
    """
    Load all FAERS tables for a quarter into PostgreSQL.
    
    Args:
        tables: Dict from parse_faers.parse_quarter()
        quarter: Quarter identifier e.g. '2026q1'
        force: If True, delete existing data before loading
        skip_views: If True, skip refreshing materialized views (faster for batch loads)
    
    Returns:
        Dictionary of {table_name: rows_loaded}
    """
    conn = get_connection()
    stats = {}
    
    try:
        # Auto-apply schema on first run (safe no-op if already exists)
        ensure_schema_exists(conn)
        
        # Check if already loaded
        if not force and quarter_already_loaded(conn, quarter):
            logger.info(f"Quarter {quarter} already loaded. Use force=True to reload.")
            return {}
        
        if force:
            delete_quarter(conn, quarter)
        
        # Load order matters: DEMO first (FK parent), then children
        LOAD_ORDER = [
            ("DEMO", "faers_demo"),
            ("DRUG", "faers_drug"),
            ("REAC", "faers_reac"),
            ("OUTC", "faers_outc"),
            ("THER", "faers_ther"),
            ("INDI", "faers_indi"),
            ("RPSR", "faers_rpsr"),
        ]
        
        total_rows = 0
        start_total = time.time()
        
        logger.info(f"{'='*60}")
        logger.info(f"Loading quarter {quarter} into PostgreSQL")
        logger.info(f"{'='*60}")
        
        for i, (df_key, table_name) in enumerate(LOAD_ORDER):
            if status_callback:
                progress = int(40 + (i / len(LOAD_ORDER)) * 40)
                status_callback("Loading", f"Bulk loading {table_name}...", progress)
                
            df = tables.get(df_key)
            if df is None or len(df) == 0:
                logger.warning(f"  Skipping {table_name} — no data")
                continue
            
            rows = bulk_load_dataframe(df, table_name, conn)
            stats[table_name] = rows
            total_rows += rows
        
        elapsed = time.time() - start_total
        logger.info(f"\n{'='*60}")
        logger.info(f"Load complete: {total_rows:,} total rows in {elapsed:.1f}s")
        logger.info(f"{'='*60}\n")
        
        # Refresh materialized views
        if not skip_views:
            refresh_materialized_views(conn, status_callback)
        
        return stats
    
    finally:
        conn.close()

if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from ingestion.parse_faers import parse_quarter
    
    quarter = sys.argv[1] if len(sys.argv) > 1 else "2026q1"
    force = "--force" in sys.argv
    
    ascii_dir = f"./data/raw/{quarter}/ascii"
    tables = parse_quarter(ascii_dir, quarter)
    stats = load_quarter(tables, quarter, force=force)
    
    print("\nLoad statistics:")
    print(json.dumps(stats, indent=2))
