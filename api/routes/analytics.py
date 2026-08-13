"""
Pre-built analytics endpoints for FAERS data

All endpoints use materialized views for <100ms responses.
Results are cached in Redis.
"""

import json

import psycopg2
import redis
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_db, get_redis

router = APIRouter()

DEFAULT_QUARTER = "2026q1"
CACHE_TTL = 900  # 15 minutes

# Response Models
class DrugReactionRow(BaseModel):
    drug: str
    reaction: str
    report_count: int
    quarter: str | None = None

class DrugOutcomeRow(BaseModel):
    drug: str
    outcome: str
    outcome_code: str
    report_count: int

class SignalRow(BaseModel):
    drug: str
    reaction: str
    report_count: int
    prr: float
    ror: float | None = None
    is_signal: bool

class CountryRow(BaseModel):
    country: str
    report_count: int
    death_count: int
    hospitalization_count: int

class QuarterlyTrend(BaseModel):
    quarter: str
    total_cases: int
    deaths: int
    hospitalizations: int
    life_threatening: int
    avg_age: float | None = None

# Helper
def cached_query(
    cache: redis.Redis,
    cache_key: str,
    conn: psycopg2.extensions.connection,
    sql: str,
    ttl: int = CACHE_TTL,
) -> list:
    """Execute query with Redis cache layer."""
    if cache:
        try:
            cached = cache.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        conn.rollback()
        return []

    if cache and rows:
        try:
            cache.setex(cache_key, ttl, json.dumps(rows, default=str))
        except Exception:
            pass

    return rows

# Endpoints
@router.get("/top-drugs", summary="Top drugs by adverse event report count")
async def top_drugs(
    quarter: str | None = Query(None, example="2026q1"),
    role: str = Query("PS", enum=["PS", "SS", "C", "all"]),
    limit: int = Query(20, ge=1, le=200),
    conn=Depends(get_db),
    cache=Depends(get_redis),
):
    """
    Returns drugs ranked by number of adverse event reports.
    Use `role=PS` for Primary Suspect drugs (most meaningful signal).
    """
    quarter_filter = f"AND quarter = '{quarter}'" if quarter else ""
    
    # mv_top_drugs is pre-aggregated and doesn't have role_cod.
    # We filter using HAVING and order by the specific role count.
    if role == "PS":
        having_clause = "HAVING SUM(ps_count) > 0"
        order_by = "SUM(ps_count) DESC"
    elif role == "SS":
        having_clause = "HAVING SUM(ss_count) > 0"
        order_by = "SUM(ss_count) DESC"
    elif role == "C":
        having_clause = "HAVING SUM(concomitant_count) > 0"
        order_by = "SUM(concomitant_count) DESC"
    else:
        having_clause = ""
        order_by = "SUM(report_count) DESC"

    sql = f"""
        SELECT drugname_clean AS drug, prod_ai_clean AS active_ingredient,
               SUM(report_count) AS total_reports,
               SUM(ps_count) AS primary_suspect_reports,
               quarter
        FROM mv_top_drugs
        WHERE 1=1 {quarter_filter}
          AND drugname_clean != ''
        GROUP BY drugname_clean, prod_ai_clean, quarter
        {having_clause}
        ORDER BY {order_by}
        LIMIT {limit}
    """

    cache_key = f"faers:top_drugs:{quarter}:{role}:{limit}"
    rows = cached_query(cache, cache_key, conn, sql)
    return {"data": rows, "count": len(rows), "quarter": quarter or "all"}

@router.get("/drug/{drug_name}/reactions", summary="Adverse reactions for a specific drug")
async def drug_reactions(
    drug_name: str,
    quarter: str | None = Query(None),
    role: str = Query("PS", enum=["PS", "SS", "C", "all"]),
    limit: int = Query(30, ge=1, le=200),
    conn=Depends(get_db),
    cache=Depends(get_redis),
):
    """Get all MedDRA reaction terms reported for a specific drug."""
    quarter_filter = f"AND quarter = '{quarter}'" if quarter else ""
    role_filter = f"AND role_cod = '{role}'" if role != "all" else ""

    sql = f"""
        SELECT reaction_term AS reaction,
               SUM(report_count) AS report_count,
               STRING_AGG(DISTINCT quarter, ', ' ORDER BY quarter) AS quarters
        FROM mv_drug_reaction_pairs
        WHERE drugname_clean ILIKE '%{drug_name.upper()}%'
          {role_filter} {quarter_filter}
        GROUP BY reaction_term
        ORDER BY report_count DESC
        LIMIT {limit}
    """

    cache_key = f"faers:drug_reactions:{drug_name}:{quarter}:{role}"
    rows = cached_query(cache, cache_key, conn, sql)

    if not rows:
        raise HTTPException(404, f"No reactions found for drug '{drug_name}'. Check spelling or try the active ingredient name.")

    return {"drug": drug_name.upper(), "data": rows, "count": len(rows)}

@router.get("/drug/{drug_name}/outcomes", summary="Patient outcomes for a specific drug")
async def drug_outcomes(
    drug_name: str,
    quarter: str | None = Query(None),
    conn=Depends(get_db),
    cache=Depends(get_redis),
):
    """Get patient outcome breakdown (death, hospitalization, etc.) for a drug."""
    quarter_filter = f"AND quarter = '{quarter}'" if quarter else ""

    sql = f"""
        SELECT outc_cod AS outcome_code,
               outcome_label AS outcome,
               SUM(report_count) AS report_count
        FROM mv_drug_outcomes
        WHERE drugname_clean ILIKE '%{drug_name.upper()}%'
          AND role_cod = 'PS'
          {quarter_filter}
        GROUP BY outc_cod, outcome_label
        ORDER BY report_count DESC
    """

    cache_key = f"faers:drug_outcomes:{drug_name}:{quarter}"
    rows = cached_query(cache, cache_key, conn, sql)
    return {"drug": drug_name.upper(), "data": rows}

@router.get("/drug/{drug_name}/signal", summary="Safety signal detection (PRR/ROR) for a drug")
async def drug_signal(
    drug_name: str,
    quarter: str | None = Query(None),
    min_reports: int = Query(3, ge=1),
    signals_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    conn=Depends(get_db),
    cache=Depends(get_redis),
):
    """
    Disproportionality analysis using PRR and ROR.
    
    - **PRR >= 2** and **N >= 3** = Evans criteria for signal
    - **ROR** = Reporting Odds Ratio (more robust at small N)
    """
    quarter_filter = f"AND quarter = '{quarter}'" if quarter else ""
    signal_filter = "AND is_signal = TRUE" if signals_only else ""

    sql = f"""
        SELECT reaction_term AS reaction,
               SUM(drug_reaction_count) AS report_count,
               MAX(prr) AS prr,
               MAX(ror) AS ror,
               BOOL_OR(is_signal) AS is_signal,
               STRING_AGG(DISTINCT quarter, ', ') AS quarters
        FROM mv_signal_prr
        WHERE drugname_clean ILIKE '%{drug_name.upper()}%'
          {quarter_filter} {signal_filter}
        GROUP BY reaction_term
        HAVING SUM(drug_reaction_count) >= {min_reports}
        ORDER BY prr DESC NULLS LAST
        LIMIT {limit}
    """

    cache_key = f"faers:signal:{drug_name}:{quarter}:{min_reports}:{signals_only}"
    rows = cached_query(cache, cache_key, conn, sql)

    signals = [r for r in rows if r.get("is_signal")]
    return {
        "drug": drug_name.upper(),
        "data": rows,
        "signal_count": len(signals),
        "note": "PRR >= 2 with N >= 3 indicates a potential safety signal (Evans criteria). "
                "This is a statistical association, not proven causation.",
    }

@router.get("/drug/{drug_name}/demographics", summary="Patient demographics for a drug")
async def drug_demographics(
    drug_name: str,
    quarter: str | None = Query(None),
    conn=Depends(get_db),
    cache=Depends(get_redis),
):
    """Age group and sex breakdown of patients reporting reactions to a drug."""
    quarter_filter = f"AND quarter = '{quarter}'" if quarter else ""

    sql = f"""
        SELECT age_group, sex,
               SUM(report_count) AS report_count,
               ROUND(AVG(avg_age)::NUMERIC, 1) AS avg_age,
               ROUND(AVG(median_age)::NUMERIC, 1) AS median_age
        FROM mv_age_sex_distribution
        WHERE drugname_clean ILIKE '%{drug_name.upper()}%'
          {quarter_filter}
        GROUP BY age_group, sex
        ORDER BY report_count DESC
    """

    cache_key = f"faers:demographics:{drug_name}:{quarter}"
    rows = cached_query(cache, cache_key, conn, sql)
    return {"drug": drug_name.upper(), "data": rows}

@router.get("/deaths/top-drugs", summary="Drugs with most death-associated reports")
async def death_reports(
    quarter: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    conn=Depends(get_db),
    cache=Depends(get_redis),
):
    """Critical safety view: drugs with highest death-associated adverse event reports."""
    quarter_filter = f"AND quarter = '{quarter}'" if quarter else ""

    sql = f"""
        SELECT drugname_clean AS drug,
               SUM(death_reports) AS death_reports,
               STRING_AGG(DISTINCT quarter, ', ' ORDER BY quarter) AS quarters
        FROM mv_death_by_drug
        WHERE 1=1 {quarter_filter}
          AND drugname_clean != ''
        GROUP BY drugname_clean
        ORDER BY death_reports DESC
        LIMIT {limit}
    """

    cache_key = f"faers:deaths:{quarter}:{limit}"
    rows = cached_query(cache, cache_key, conn, sql)
    return {
        "data": rows,
        "warning": "These are reports where death occurred AND the drug was mentioned. "
                   "This does NOT imply the drug caused the death.",
    }

@router.get("/countries", summary="Report distribution by country")
async def reports_by_country(
    quarter: str | None = Query(None),
    limit: int = Query(50, ge=1, le=300),
    conn=Depends(get_db),
    cache=Depends(get_redis),
):
    """Geographic distribution of adverse event reports."""
    quarter_filter = f"AND quarter = '{quarter}'" if quarter else ""

    sql = f"""
        SELECT reporter_country AS country,
               SUM(report_count) AS report_count,
               SUM(death_count) AS death_count,
               SUM(hospitalization_count) AS hospitalization_count,
               SUM(life_threatening_count) AS life_threatening_count
        FROM mv_reports_by_country
        WHERE reporter_country IS NOT NULL
          AND reporter_country != ''
          {quarter_filter}
        GROUP BY reporter_country
        ORDER BY report_count DESC
        LIMIT {limit}
    """

    cache_key = f"faers:countries:{quarter}"
    rows = cached_query(cache, cache_key, conn, sql)
    return {"data": rows, "count": len(rows)}

@router.get("/trends", summary="Quarterly reporting trends over time")
async def quarterly_trends(
    conn=Depends(get_db),
    cache=Depends(get_redis),
):
    """Time-series view of FAERS reporting trends across quarters."""
    sql = """
        SELECT quarter, total_cases, deaths, hospitalizations,
               life_threatening, female_cases, male_cases,
               ROUND(avg_age::NUMERIC, 1) AS avg_age,
               reporting_countries
        FROM mv_quarterly_trends
        ORDER BY quarter
    """
    cache_key = "faers:trends"
    rows = cached_query(cache, cache_key, conn, sql, ttl=3600)
    return {"data": rows}

@router.get("/top-reactions", summary="Most commonly reported reactions overall")
async def top_reactions(
    quarter: str | None = Query(None),
    limit: int = Query(30, ge=1, le=200),
    conn=Depends(get_db),
    cache=Depends(get_redis),
):
    """Top MedDRA reaction terms across all drugs."""
    quarter_filter = f"AND quarter = '{quarter}'" if quarter else ""

    sql = f"""
        SELECT reaction_term AS reaction,
               SUM(report_count) AS report_count
        FROM mv_top_reactions
        WHERE reaction_term IS NOT NULL AND reaction_term != ''
          {quarter_filter}
        GROUP BY reaction_term
        ORDER BY report_count DESC
        LIMIT {limit}
    """
    cache_key = f"faers:top_reactions:{quarter}:{limit}"
    rows = cached_query(cache, cache_key, conn, sql)
    return {"data": rows, "count": len(rows)}

@router.get("/summary", summary="Overall database summary statistics")
async def db_summary(
    conn=Depends(get_db),
    cache=Depends(get_redis),
):
    """High-level statistics about the loaded FAERS data."""
    sql = """
        SELECT
            (SELECT COUNT(*) FROM faers_demo) AS total_cases,
            (SELECT COUNT(*) FROM faers_drug) AS total_drug_records,
            (SELECT COUNT(*) FROM faers_reac) AS total_reaction_records,
            (SELECT COUNT(DISTINCT reporter_country) FROM faers_demo) AS total_countries,
            (SELECT COUNT(DISTINCT drugname_clean) FROM faers_drug) AS unique_drugs,
            (SELECT COUNT(DISTINCT pt_clean) FROM faers_reac) AS unique_reactions,
            (SELECT STRING_AGG(DISTINCT quarter, ', ' ORDER BY quarter) FROM faers_demo) AS loaded_quarters
    """
    cache_key = "faers:summary"
    rows = cached_query(cache, cache_key, conn, sql, ttl=3600)
    if not rows:
        return {
            "total_cases": 0,
            "total_drug_records": 0,
            "total_reaction_records": 0,
            "total_countries": 0,
            "unique_drugs": 0,
            "unique_reactions": 0,
            "loaded_quarters": None,
        }
    return rows[0]
