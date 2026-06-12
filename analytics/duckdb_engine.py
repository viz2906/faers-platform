"""
High-performance analytical queries via DuckDB

DuckDB is a columnar analytical database that can:
1. Query PostgreSQL directly (via pg_scanner extension)
2. Query Parquet files on disk or S3
3. Run in-memory with vectorized execution

Use this for: heavy aggregations, cross-quarter scans, PRR recalculation,
multi-year trend analysis — anything too slow for PostgreSQL.
"""

import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import duckdb
from loguru import logger


# DuckDB Connection (in-process, no server needed)
class DuckDBEngine:
    """
    Analytical query engine using DuckDB.
    
    Two modes:
    1. PARQUET mode: queries pre-exported Parquet files
    2. POSTGRES mode: queries PostgreSQL directly via pg_scanner (requires pg_duckdb extension)
    """

    def __init__(
        self,
        parquet_dir: str = "./data/parquet",
        mode: str = "parquet",  # "parquet" or "postgres"
        pg_connection_string: Optional[str] = None,
        memory_limit: str = "4GB",
        threads: int = 4,
    ):
        self.parquet_dir = Path(parquet_dir)
        self.mode = mode
        self.pg_dsn = pg_connection_string or os.getenv("POSTGRES_DSN")
        self.memory_limit = memory_limit
        self.threads = threads
        self._conn = None

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Create and configure a DuckDB connection."""
        conn = duckdb.connect(":memory:")

        # Configure performance
        conn.execute(f"SET memory_limit='{self.memory_limit}'")
        conn.execute(f"SET threads={self.threads}")
        conn.execute("SET enable_progress_bar=true")

        if self.mode == "postgres" and self.pg_dsn:
            # Load PostgreSQL scanner (reads PG tables directly)
            conn.execute("INSTALL postgres")
            conn.execute("LOAD postgres")
            conn.execute(f"""
                ATTACH 'host={os.getenv('POSTGRES_HOST', 'localhost')}
                        port={os.getenv('POSTGRES_PORT', 5432)}
                        dbname={os.getenv('POSTGRES_DB', 'faers')}
                        user={os.getenv('POSTGRES_USER', 'faers_user')}
                        password={os.getenv('POSTGRES_PASSWORD', 'faers_secret_pw')}'
                AS faers_pg (TYPE postgres)
            """)
            logger.info("DuckDB connected to PostgreSQL via pg_scanner")

        elif self.mode == "parquet":
            # Register Parquet files as views
            self._register_parquet_views(conn)
            logger.info(f"DuckDB connected to Parquet files at {self.parquet_dir}")

        self._conn = conn
        return conn

    def _register_parquet_views(self, conn: duckdb.DuckDBPyConnection):
        """Register Parquet files as SQL views in DuckDB."""
        table_files = {
            "demo": "demo",
            "drug": "drug",
            "reac": "reac",
            "outc": "outc",
            "ther": "ther",
            "indi": "indi",
        }

        for view_name, file_prefix in table_files.items():
            parquet_pattern = str(self.parquet_dir / f"{file_prefix}" / "**" / "*.parquet")
            all_files = list(self.parquet_dir.glob(f"{file_prefix}/**/*.parquet"))

            if not all_files:
                logger.warning(f"No Parquet files found for {view_name}. Run parquet_export.py first.")
                continue

            # Hive-partitioned Parquet (quarter=2026q1/file.parquet)
            conn.execute(f"""
                CREATE OR REPLACE VIEW faers_{view_name} AS
                SELECT * FROM read_parquet('{parquet_pattern}', hive_partitioning=true)
            """)
            logger.debug(f"  Registered view: faers_{view_name} ({len(all_files)} files)")

    def query(self, sql: str) -> pd.DataFrame:
        """Execute a SQL query and return results as DataFrame."""
        if self._conn is None:
            self.connect()

        start = time.time()
        result = self._conn.execute(sql).fetchdf()
        elapsed = time.time() - start
        logger.info(f"DuckDB query: {len(result):,} rows in {elapsed:.2f}s")
        return result

    def query_to_list(self, sql: str) -> tuple[list[str], list[tuple]]:
        """Execute query and return (columns, rows) for API compatibility."""
        df = self.query(sql)
        return list(df.columns), [tuple(row) for row in df.itertuples(index=False)]

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


# Pre-built Heavy Analytics Queries
class FAERSHeavyAnalytics:
    """
    Complex analytics that benefit from DuckDB's columnar execution.
    These are too slow for real-time PostgreSQL queries.
    """

    def __init__(self, engine: DuckDBEngine):
        self.engine = engine
        if self.engine._conn is None:
            self.engine.connect()

    def prr_full_recalculation(self, min_reports: int = 3) -> pd.DataFrame:
        """
        Full PRR calculation across all drug-reaction pairs.
        This is the core signal detection calculation.
        
        Much faster in DuckDB than PostgreSQL for large datasets.
        """
        sql = f"""
        WITH
        totals AS (
            SELECT COUNT(DISTINCT primaryid) AS N
            FROM faers_demo
        ),
        drug_totals AS (
            SELECT drugname_clean, COUNT(DISTINCT primaryid) AS n_drug
            FROM faers_drug
            WHERE role_cod = 'PS' AND drugname_clean IS NOT NULL AND drugname_clean != ''
            GROUP BY drugname_clean
        ),
        reac_totals AS (
            SELECT pt_clean AS reaction, COUNT(DISTINCT primaryid) AS n_reac
            FROM faers_reac
            GROUP BY pt_clean
        ),
        drug_reac AS (
            SELECT d.drugname_clean, r.pt_clean AS reaction,
                   COUNT(DISTINCT d.primaryid) AS a
            FROM faers_drug d
            JOIN faers_reac r ON d.primaryid = r.primaryid
            WHERE d.role_cod = 'PS'
              AND d.drugname_clean IS NOT NULL AND d.drugname_clean != ''
            GROUP BY d.drugname_clean, r.pt_clean
            HAVING COUNT(DISTINCT d.primaryid) >= {min_reports}
        )
        SELECT
            dr.drugname_clean AS drug,
            dr.reaction,
            dr.a AS drug_reaction_count,
            dt.n_drug AS drug_total,
            rt.n_reac AS reaction_total,
            t.N AS grand_total,
            -- PRR
            ROUND((dr.a * 1.0 / dt.n_drug) / (rt.n_reac * 1.0 / t.N), 3) AS prr,
            -- ROR
            ROUND(
                (dr.a * (t.N - rt.n_reac - dt.n_drug + dr.a)) * 1.0 /
                NULLIF((dt.n_drug - dr.a) * (rt.n_reac - dr.a), 0)
            , 3) AS ror,
            -- Chi-squared (Yates corrected)
            -- Signal flag (PRR >= 2, N >= 3)
            CASE WHEN dr.a >= 3 AND
                      (dr.a * 1.0 / dt.n_drug) / (rt.n_reac * 1.0 / t.N) >= 2.0
                 THEN TRUE ELSE FALSE
            END AS is_signal
        FROM drug_reac dr
        JOIN drug_totals dt ON dr.drugname_clean = dt.drugname_clean
        JOIN reac_totals rt ON dr.reaction = rt.reaction
        CROSS JOIN totals t
        ORDER BY prr DESC NULLS LAST
        """

        logger.info("Running full PRR calculation via DuckDB...")
        start = time.time()
        result = self.engine.query(sql)
        logger.info(f"PRR calculated: {len(result):,} drug-reaction pairs in {time.time()-start:.1f}s")
        return result

    def cross_quarter_drug_trend(self, drug_name: str) -> pd.DataFrame:
        """Track a drug's adverse event count across all quarters."""
        sql = f"""
        SELECT
            d.quarter,
            COUNT(DISTINCT d.primaryid) AS report_count,
            COUNT(DISTINCT CASE WHEN o.outc_cod = 'DE' THEN d.primaryid END) AS deaths,
            COUNT(DISTINCT CASE WHEN o.outc_cod = 'HO' THEN d.primaryid END) AS hospitalizations,
            COUNT(DISTINCT r.pt_clean) AS unique_reactions_reported
        FROM faers_drug d
        LEFT JOIN faers_outc o ON d.primaryid = o.primaryid
        LEFT JOIN faers_reac r ON d.primaryid = r.primaryid
        WHERE d.drugname_clean ILIKE '%{drug_name.upper()}%'
          AND d.role_cod = 'PS'
        GROUP BY d.quarter
        ORDER BY d.quarter
        """
        return self.engine.query(sql)

    def polypharmacy_analysis(self, min_drug_count: int = 5) -> pd.DataFrame:
        """Identify cases with high drug burden (polypharmacy)."""
        sql = f"""
        SELECT
            primaryid,
            COUNT(*) AS drug_count,
            STRING_AGG(drugname_clean, ' | ' ORDER BY drug_seq) AS drug_list
        FROM faers_drug
        GROUP BY primaryid
        HAVING COUNT(*) >= {min_drug_count}
        ORDER BY drug_count DESC
        LIMIT 1000
        """
        return self.engine.query(sql)

    def drug_drug_interaction_pairs(self, min_co_reports: int = 10) -> pd.DataFrame:
        """
        Find drug pairs frequently reported together in serious adverse events.
        Useful for identifying potential drug-drug interactions.
        """
        sql = f"""
        WITH serious_cases AS (
            SELECT DISTINCT primaryid
            FROM faers_outc
            WHERE outc_cod IN ('DE', 'LT', 'HO')
        ),
        suspect_drugs AS (
            SELECT primaryid, drugname_clean
            FROM faers_drug
            WHERE role_cod IN ('PS', 'SS')
              AND drugname_clean IS NOT NULL AND drugname_clean != ''
              AND primaryid IN (SELECT primaryid FROM serious_cases)
        )
        SELECT
            a.drugname_clean AS drug_a,
            b.drugname_clean AS drug_b,
            COUNT(*) AS co_report_count
        FROM suspect_drugs a
        JOIN suspect_drugs b ON a.primaryid = b.primaryid
            AND a.drugname_clean < b.drugname_clean   -- prevent duplicates
        GROUP BY a.drugname_clean, b.drugname_clean
        HAVING COUNT(*) >= {min_co_reports}
        ORDER BY co_report_count DESC
        LIMIT 500
        """
        return self.engine.query(sql)


# CLI test
if __name__ == "__main__":
    engine = DuckDBEngine(parquet_dir="./data/parquet", mode="parquet")
    engine.connect()

    analytics = FAERSHeavyAnalytics(engine)

    print("Running cross-quarter drug trend for WARFARIN...")
    df = analytics.cross_quarter_drug_trend("WARFARIN")
    print(df.to_string())

    engine.close()
