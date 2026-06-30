"""
Export PostgreSQL FAERS tables to Parquet for DuckDB/S3

Run this after loading new quarters to keep the analytical layer in sync.
Parquet files are partitioned by quarter for efficient range scans.

Usage:
    python scaling/parquet_export.py --quarter 2026q1
    python scaling/parquet_export.py --all    # Export all loaded quarters
"""

import os
import sys
import argparse
import time
from pathlib import Path

import psycopg2
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

PARQUET_DIR = Path(os.getenv("FAERS_PARQUET_DIR", "./data/parquet"))

# Tables to export and their primary columns
EXPORT_TABLES = {
    "demo": {
        "table": "faers_demo",
        "select": """
            SELECT primaryid, caseid, caseversion, quarter,
                   i_f_code, event_dt, fda_dt, rept_cod,
                   age_years, age_group, sex, weight_kg,
                   reporter_country, occr_country, occp_cod
            FROM faers_demo
            WHERE quarter = '{quarter}'
        """,
        "partition_cols": ["quarter"],
    },
    "drug": {
        "table": "faers_drug",
        "select": """
            SELECT primaryid, caseid, drug_seq, quarter,
                   role_cod, drug_role, drugname_clean, prod_ai_clean,
                   route_clean, dose_amt, dose_unit, nda_num
            FROM faers_drug
            WHERE quarter = '{quarter}'
        """,
        "partition_cols": ["quarter"],
    },
    "reac": {
        "table": "faers_reac",
        "select": """
            SELECT primaryid, caseid, quarter, pt_clean AS pt_clean
            FROM faers_reac
            WHERE quarter = '{quarter}'
        """,
        "partition_cols": ["quarter"],
    },
    "outc": {
        "table": "faers_outc",
        "select": """
            SELECT primaryid, caseid, quarter, outc_cod, outcome_label
            FROM faers_outc
            WHERE quarter = '{quarter}'
        """,
        "partition_cols": ["quarter"],
    },
    "indi": {
        "table": "faers_indi",
        "select": """
            SELECT primaryid, caseid, drug_seq, quarter, indi_pt_clean
            FROM faers_indi
            WHERE quarter = '{quarter}'
        """,
        "partition_cols": ["quarter"],
    },
}

def get_loaded_quarters(conn) -> list[str]:
    """Get all quarters currently loaded in PostgreSQL."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT quarter FROM faers_demo ORDER BY quarter")
        return [row[0] for row in cur.fetchall()]

def export_table_quarter(
    conn,
    table_key: str,
    config: dict,
    quarter: str,
    overwrite: bool = False,
) -> int:
    """Export one table's data for one quarter to Parquet."""
    output_dir = PARQUET_DIR / table_key / f"quarter={quarter}"
    output_file = output_dir / "data.parquet"

    if output_file.exists() and not overwrite:
        logger.info(f"  [SKIP] {table_key}/{quarter} already exported")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    # Execute query
    sql = config["select"].format(quarter=quarter)
    logger.info(f"  Exporting {table_key} for {quarter}...")

    start = time.time()
    df = pd.read_sql(sql, conn)

    if df.empty:
        logger.warning(f"  No data for {table_key} quarter={quarter}")
        return 0

    # Convert to Parquet with optimal compression
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(
        table,
        str(output_file),
        compression="snappy",           # Fast read/write, good compression
        row_group_size=100_000,         # Optimal for analytical queries
        write_statistics=True,          # Enable predicate pushdown
        use_dictionary=True,            # Efficient for categorical columns
    )

    file_size_mb = output_file.stat().st_size / 1024 / 1024
    elapsed = time.time() - start
    logger.info(
        f"   {table_key}/{quarter}: {len(df):,} rows → "
        f"{file_size_mb:.1f} MB Parquet in {elapsed:.1f}s"
    )
    return len(df)

def export_quarter(quarter: str, overwrite: bool = False) -> dict:
    """Export all tables for a quarter to Parquet."""
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        database=os.getenv("POSTGRES_DB", "faers"),
        user=os.getenv("POSTGRES_USER", "faers_user"),
        password=os.getenv("POSTGRES_PASSWORD", "faers_secret_pw"),
    )

    logger.info(f"\n{'='*50}")
    logger.info(f"Exporting quarter {quarter} to Parquet")
    logger.info(f"Destination: {PARQUET_DIR}")
    logger.info(f"{'='*50}")

    stats = {}
    total_rows = 0
    start = time.time()

    for table_key, config in EXPORT_TABLES.items():
        rows = export_table_quarter(conn, table_key, config, quarter, overwrite)
        stats[table_key] = rows
        total_rows += rows

    conn.close()
    elapsed = time.time() - start

    logger.info(f"\nExport complete: {total_rows:,} rows in {elapsed:.1f}s")
    return stats

def main():
    parser = argparse.ArgumentParser(description="Export FAERS data to Parquet")
    parser.add_argument("--quarter", type=str, help="Quarter to export (e.g. 2026q1)")
    parser.add_argument("--all", action="store_true", help="Export all loaded quarters")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Parquet files")
    args = parser.parse_args()

    if args.all:
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            database=os.getenv("POSTGRES_DB", "faers"),
            user=os.getenv("POSTGRES_USER", "faers_user"),
            password=os.getenv("POSTGRES_PASSWORD", "faers_secret_pw"),
        )
        quarters = get_loaded_quarters(conn)
        conn.close()

        logger.info(f"Exporting {len(quarters)} quarters: {quarters}")
        for q in quarters:
            export_quarter(q, overwrite=args.overwrite)
    elif args.quarter:
        export_quarter(args.quarter, overwrite=args.overwrite)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
