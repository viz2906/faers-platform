"""
Core NLP → SQL → Execute → Explain pipeline

The main entry point for all natural language queries against FAERS data.
Orchestrates: LLM → SQL → Validate → Route → Execute → Explain → Cache
"""

import os
import time
import json
import hashlib
import re
from typing import Optional, Any
from datetime import datetime

import psycopg2
import psycopg2.extras
import redis
from openai import OpenAI
from loguru import logger
from dotenv import load_dotenv

from nlp.system_prompt import FAERS_SYSTEM_PROMPT
from nlp.sql_validator import validate_sql, sanitize_user_input, SQLValidationError

load_dotenv()


# Query Result Type
class QueryResult:
    def __init__(
        self,
        question: str,
        sql: str,
        columns: list[str],
        data: list[tuple],
        explanation: str,
        response_time_ms: int,
        from_cache: bool = False,
        query_type: str = "unknown",
        warning: Optional[str] = None,
        error: Optional[str] = None,
    ):
        self.question = question
        self.sql = sql
        self.columns = columns
        self.data = data
        self.explanation = explanation
        self.response_time_ms = response_time_ms
        self.from_cache = from_cache
        self.query_type = query_type
        self.warning = warning
        self.error = error
        self.row_count = len(data)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "sql": self.sql,
            "columns": self.columns,
            "data": [list(row) for row in self.data],
            "row_count": self.row_count,
            "explanation": self.explanation,
            "response_time_ms": self.response_time_ms,
            "from_cache": self.from_cache,
            "query_type": self.query_type,
            "warning": self.warning,
            "error": self.error,
        }


# Query Router — decides which path to use
# Patterns that suggest a materialized view can answer the question
MATERIALIZED_VIEW_PATTERNS = [
    # top/most/common + drug OR report context (supports plural 'reports')
    (r'\b(top|most|common|frequent)\b.*\b(drug|medication|reaction|adverse|reports?)\b', "mv_top_drugs"),
    # drugs with highest X (catches "drugs have the most reports")
    (r'\b(drug|medication)\b.*\b(most|highest|top|frequent)\b', "mv_top_drugs"),
    # reaction/side effect for a drug
    (r'\b(reaction|side effect|adverse event).*\bfor\b', "mv_drug_reaction_pairs"),
    # death/fatal — drug/medication optional (catches "death reports" alone)
    (r'\b(death|fatal|mortality|died)\b', "mv_death_by_drug"),
    # country/geographic reporting
    (r'\b(country|countries|nation|where)\b.*\breport', "mv_reports_by_country"),
    # safety signal metrics
    (r'\b(signal|prr|proportional|ror|ratio)\b', "mv_signal_prr"),
    # age/demographic with or without explicit drug mention (catches "age distribution for patients")
    (r'\b(age|gender|sex|demographic|distribution)\b.*\b(drug|medication|patient|aspirin|warfarin|report)\b', "mv_age_sex_distribution"),
    (r'\bage distribution\b', "mv_age_sex_distribution"),
    # time trends
    (r'\b(trend|over time|quarterly|quarter)\b', "mv_quarterly_trends"),
    # outcome/drug
    (r'\boutcome\b.*\b(drug|medication)\b', "mv_drug_outcomes"),
]


def classify_query(question: str) -> str:
    """Classify a question to determine the optimal execution path."""
    q_lower = question.lower()
    for pattern, view in MATERIALIZED_VIEW_PATTERNS:
        if re.search(pattern, q_lower):
            return f"materialized_view:{view}"
    return "raw_tables"


# Main Query Engine
class FAERSQueryEngine:
    """
    Convert natural language questions to SQL and execute against FAERS.
    
    Example:
        engine = FAERSQueryEngine.from_env()
        result = engine.query("What are the top reactions for aspirin?")
        print(result.explanation)
    """

    def __init__(
        self,
        db_conn: psycopg2.extensions.connection,
        redis_client: Optional[redis.Redis],
        llm_client: OpenAI,
        timeout_seconds: int = 5,
        enable_cache: bool = True,
        explain_results: bool = True,
    ):
        self.db = db_conn
        self.cache = redis_client
        self.llm = llm_client
        self.timeout_ms = timeout_seconds * 1000
        self.enable_cache = enable_cache
        self.explain_results = explain_results
        self.main_model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.mini_model = os.getenv("OPENAI_MINI_MODEL", "gpt-4o-mini")

    @classmethod
    def from_env(cls) -> "FAERSQueryEngine":
        """Create engine from environment variables."""
        db_conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            database=os.getenv("POSTGRES_DB", "faers"),
            user=os.getenv("POSTGRES_USER", "faers_user"),
            password=os.getenv("POSTGRES_PASSWORD", "faers_secret_pw"),
        )
        
        redis_client = None
        try:
            redis_client = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                db=int(os.getenv("REDIS_DB", 0)),
                decode_responses=True,
            )
            redis_client.ping()
            logger.info("Redis cache connected")
        except Exception as e:
            logger.warning(f"Redis not available, running without cache: {e}")
        
        llm_client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),  # Optional: for local LLMs
        )
        
        return cls(
            db_conn=db_conn,
            redis_client=redis_client,
            llm_client=llm_client,
            timeout_seconds=int(os.getenv("QUERY_TIMEOUT_SECONDS", 5)),
            enable_cache=os.getenv("ENABLE_CACHE", "true").lower() == "true",
            explain_results=os.getenv("EXPLAIN_RESULTS", "true").lower() == "true",
        )

    def query(self, question: str, quarter_filter: Optional[str] = None) -> QueryResult:
        """
        Execute a natural language query against FAERS data.
        
        Args:
            question: Natural language question
            quarter_filter: Optional quarter to scope query (e.g. '2026q1')
        
        Returns:
            QueryResult with SQL, data, and plain English explanation
        """
        global_start = time.time()
        
        # Sanitize input
        question = sanitize_user_input(question)
        if not question:
            return self._error_result("Empty question", question)
        
        # Add quarter context to question if specified
        effective_question = question
        if quarter_filter:
            effective_question = f"{question} (filter to quarter: {quarter_filter})"
        
        # Check cache
        cache_key = self._cache_key(effective_question)
        if self.enable_cache and self.cache:
            cached = self._get_cached(cache_key)
            if cached:
                cached["response_time_ms"] = int((time.time() - global_start) * 1000)
                cached["from_cache"] = True
                return QueryResult(**{k: v for k, v in cached.items() 
                                     if k in QueryResult.__init__.__code__.co_varnames})
        
        # Classify query type
        query_type = classify_query(question)
        logger.info(f"Query type: {query_type}")
        
        # Generate SQL
        try:
            sql = self._generate_sql(effective_question)
            logger.debug(f"Generated SQL:\n{sql}")
        except Exception as e:
            logger.error(f"SQL generation failed: {e}")
            return self._error_result(f"Could not generate SQL: {e}", question)
        
        # Validate SQL
        try:
            sql = validate_sql(sql)
        except SQLValidationError as e:
            logger.warning(f"SQL validation failed: {e}\nSQL: {sql}")
            return self._error_result(f"Generated SQL failed validation: {e}", question, sql)
        
        # Execute
        try:
            columns, data = self._execute(sql)
        except psycopg2.errors.QueryCanceled:
            return self._error_result(
                f"Query exceeded {self.timeout_ms // 1000}s timeout. "
                "Try a more specific question (e.g. add a drug name or quarter filter).",
                question, sql
            )
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            # Try to reconnect and retry once
            try:
                self._reconnect()
                columns, data = self._execute(sql)
            except Exception as e2:
                return self._error_result(f"Query execution failed: {e2}", question, sql)
        
        # Generate explanation
        explanation = ""
        if self.explain_results and data:
            try:
                explanation = self._explain_results(question, sql, columns, data)
            except Exception as e:
                explanation = f"Results returned ({len(data)} rows)."
                logger.warning(f"Explanation generation failed: {e}")
        elif not data:
            explanation = "No results found for this query. Try a different drug name or broader search terms."
        
        response_time_ms = int((time.time() - global_start) * 1000)
        
        result = QueryResult(
            question=question,
            sql=sql,
            columns=columns,
            data=data,
            explanation=explanation,
            response_time_ms=response_time_ms,
            from_cache=False,
            query_type=query_type,
            warning=self._get_faers_warning(question),
        )
        
        # Log query
        self._log_query(question, sql, response_time_ms, len(data))
        
        # Cache result
        if self.enable_cache and self.cache and not result.error:
            self._cache_result(cache_key, result)
        
        logger.info(f"Query complete: {len(data)} rows in {response_time_ms}ms")
        return result

    # ============================================================
    # SQL Generation
    # ============================================================

    def _generate_sql(self, question: str) -> str:
        """Call LLM to generate SQL from natural language."""
        response = self.llm.chat.completions.create(
            model=self.main_model,
            messages=[
                {"role": "system", "content": FAERS_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0,          # Deterministic — we want consistent SQL
            max_tokens=1500,
            timeout=15,             # LLM call timeout
        )
        
        sql = response.choices[0].message.content.strip()
        
        # Strip markdown code blocks if LLM wrapped it
        sql = re.sub(r"```sql\s*", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"```\s*", "", sql)
        sql = sql.strip()
        
        return sql

    # ============================================================
    # Execution
    # ============================================================

    def _execute(self, sql: str) -> tuple[list[str], list[tuple]]:
        """Execute SQL with timeout enforcement."""
        with self.db.cursor() as cur:
            # Set per-statement timeout
            cur.execute(f"SET LOCAL statement_timeout = {self.timeout_ms}")
            cur.execute(sql)
            
            columns = [desc[0] for desc in cur.description] if cur.description else []
            data = cur.fetchall()
        
        return columns, data

    def _reconnect(self):
        """Attempt to reconnect to the database."""
        try:
            self.db = psycopg2.connect(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", 5432)),
                database=os.getenv("POSTGRES_DB", "faers"),
                user=os.getenv("POSTGRES_USER", "faers_user"),
                password=os.getenv("POSTGRES_PASSWORD", "faers_secret_pw"),
            )
        except Exception as e:
            raise Exception(f"Database reconnection failed: {e}")

    # ============================================================
    # Result Explanation
    # ============================================================

    def _explain_results(
        self, question: str, sql: str,
        columns: list[str], data: list[tuple]
    ) -> str:
        """Generate a plain English explanation of query results using LLM."""
        
        # Build a compact result preview for the LLM
        preview_rows = [dict(zip(columns, row)) for row in data[:5]]
        total_rows = len(data)
        
        # Serialize preview (handle dates, decimals, etc.)
        def serialize(obj):
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            return str(obj)
        
        preview_json = json.dumps(preview_rows, indent=2, default=serialize)
        
        prompt = f"""The user asked this question about FDA drug adverse event data: 
"{question}"

The database returned {total_rows} result(s). First 5 rows:
{preview_json}

Column meanings in this context:
- report_count / total_reports: Number of adverse event reports in the FDA database
- prr: Proportional Reporting Ratio (>2 with N≥3 = potential safety signal)
- ror: Reporting Odds Ratio (safety signal metric, similar to PRR)
- death_reports: Reports where patient death was the outcome

Write a clear 2-3 sentence plain English summary of what these results show.
Be specific about the numbers. 
Important caveat to include: FAERS reports association, not causation — higher counts reflect reporting patterns, not proven drug effects.
Keep it factual and concise."""

        response = self.llm.chat.completions.create(
            model=self.mini_model,     # Cheaper model for explanation
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=250,
            timeout=10,
        )
        
        return response.choices[0].message.content.strip()

    # ============================================================
    # Caching
    # ============================================================

    def _cache_key(self, question: str) -> str:
        return f"faers:query:{hashlib.md5(question.encode()).hexdigest()}"

    def _get_cached(self, key: str) -> Optional[dict]:
        try:
            raw = self.cache.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return None

    def _cache_result(self, key: str, result: QueryResult, ttl: int = 3600):
        try:
            serializable = result.to_dict()
            self.cache.setex(key, ttl, json.dumps(serializable, default=str))
        except Exception as e:
            logger.debug(f"Cache write failed: {e}")

    # ============================================================
    # Helpers
    # ============================================================

    def _get_faers_warning(self, question: str) -> Optional[str]:
        """Return contextual FAERS data interpretation warning."""
        q_lower = question.lower()
        if any(w in q_lower for w in ["cause", "causes", "responsible", "proven", "definitely"]):
            return ("FAERS data shows reporting associations, not proven causation. "
                    "A high report count indicates surveillance interest, not confirmed drug-related effects.")
        if "death" in q_lower or "fatal" in q_lower:
            return ("Death reports in FAERS include all fatalities where the drug was mentioned, "
                    "not necessarily drug-caused deaths. Clinical context is required.")
        return None

    def _log_query(self, question: str, sql: str, response_ms: int, row_count: int):
        """Log query to database for analytics."""
        try:
            with self.db.cursor() as cur:
                cur.execute("""
                    INSERT INTO nlq_query_log
                        (query_text, generated_sql, response_time_ms, rows_returned)
                    VALUES (%s, %s, %s, %s)
                """, (question[:2000], sql[:5000], response_ms, row_count))
            self.db.commit()
        except Exception:
            pass  # Don't fail on logging errors

    def _error_result(
        self, message: str, question: str, sql: str = ""
    ) -> QueryResult:
        return QueryResult(
            question=question,
            sql=sql,
            columns=[],
            data=[],
            explanation="",
            response_time_ms=0,
            error=message,
        )


# CLI for testing
if __name__ == "__main__":
    import sys
    
    question = " ".join(sys.argv[1:]) or "What are the top 10 drugs by adverse event reports?"
    
    print(f"\n{'='*60}")
    print(f"Question: {question}")
    print(f"{'='*60}\n")
    
    engine = FAERSQueryEngine.from_env()
    result = engine.query(question)
    
    if result.error:
        print(f"ERROR: {result.error}")
    else:
        print(f"SQL:\n{result.sql}\n")
        print(f"Columns: {result.columns}")
        print(f"Rows: {result.row_count}")
        print(f"\nExplanation:\n{result.explanation}")
        if result.warning:
            print(f"\nWarning: {result.warning}")
        print(f"\nResponse time: {result.response_time_ms}ms (cache: {result.from_cache})")
