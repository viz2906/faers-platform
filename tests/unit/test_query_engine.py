"""
Unit tests for the core NLP→SQL engine

Tests the FAERSQueryEngine class in isolation using mock dependencies.
No real database, Redis, or OpenAI calls are made.
"""

import pytest
from nlp.query_engine import FAERSQueryEngine, classify_query, QueryResult


# classify_query — Query Router Tests
class TestClassifyQuery:
    """Tests for the query classifier that routes to MVs vs raw tables."""

    def test_top_drugs_routes_to_mv(self):
        assert classify_query("top drugs by reports").startswith("materialized_view")

    def test_most_common_routes_to_mv(self):
        assert classify_query("most common adverse reactions").startswith("materialized_view")

    def test_death_routes_to_mv(self):
        assert classify_query("which drugs have the most death reports").startswith("materialized_view")

    def test_country_routes_to_mv(self):
        assert classify_query("which countries report the most events").startswith("materialized_view")

    def test_prr_signal_routes_to_mv(self):
        assert classify_query("show PRR safety signals for warfarin").startswith("materialized_view")

    def test_quarterly_trend_routes_to_mv(self):
        assert classify_query("show quarterly trends over time").startswith("materialized_view")

    def test_age_demographics_routes_to_mv(self):
        assert classify_query("age distribution for patients on aspirin").startswith("materialized_view")

    def test_unknown_query_falls_back_to_raw(self):
        assert classify_query("find case 12345678") == "raw_tables"

    def test_empty_string_falls_back_to_raw(self):
        assert classify_query("") == "raw_tables"


# FAERSQueryEngine — Core Query Tests
class TestQueryEngine:
    """Tests for the main query engine pipeline."""

    def test_sql_always_returned_in_response(self, mock_engine):
        """
        SQL must always be present in every successful response.
        This is the foundation of hallucination transparency.
        """
        result = mock_engine.query("top 10 drugs by adverse event reports")
        assert result.sql, "SQL field must never be empty on a successful query"
        assert "SELECT" in result.sql.upper(), "Generated SQL must start with SELECT"

    def test_sql_contains_expected_table(self, mock_engine):
        """The generated SQL must reference a FAERS table, not a made-up one."""
        result = mock_engine.query("top drugs")
        assert "faers_drug" in result.sql.lower() or "mv_" in result.sql.lower()

    def test_result_has_data(self, mock_engine, sample_drug_rows, sample_columns):
        """Successful query must return rows and column names."""
        result = mock_engine.query("top 10 drugs")
        assert result.row_count == len(sample_drug_rows)
        assert result.columns == sample_columns
        assert result.data is not None

    def test_result_has_no_error(self, mock_engine):
        """A valid query must not produce an error."""
        result = mock_engine.query("top 10 drugs")
        assert result.error is None

    def test_empty_question_returns_error(self, mock_engine):
        """Empty input must be rejected gracefully — no SQL should be generated."""
        result = mock_engine.query("")
        assert result.error is not None
        assert result.sql == ""

    def test_whitespace_only_question_returns_error(self, mock_engine):
        """Whitespace-only input must also be rejected."""
        result = mock_engine.query("   ")
        assert result.error is not None

    def test_response_time_is_populated(self, mock_engine):
        """Response time must always be tracked."""
        result = mock_engine.query("top drugs")
        assert result.response_time_ms >= 0

    def test_from_cache_is_false_on_first_query(self, mock_engine):
        """First query should not be served from cache (cache is mocked as miss)."""
        result = mock_engine.query("top drugs")
        assert result.from_cache is False

    def test_query_type_is_set(self, mock_engine):
        """Query type must always be classified."""
        result = mock_engine.query("top drugs by reports")
        assert result.query_type is not None
        assert result.query_type != ""

    def test_to_dict_has_all_required_keys(self, mock_engine):
        """The to_dict() method must include all API response fields."""
        result = mock_engine.query("top drugs")
        d = result.to_dict()
        required_keys = {
            "question", "sql", "columns", "data", "row_count",
            "explanation", "response_time_ms", "from_cache",
            "query_type", "warning", "error"
        }
        assert required_keys.issubset(d.keys()), f"Missing keys: {required_keys - d.keys()}"

    def test_death_query_returns_warning(self, mock_engine):
        """Queries about death/fatality must include the FAERS data-interpretation warning."""
        result = mock_engine.query("which drugs have the most death reports")
        assert result.warning is not None
        assert "FAERS" in result.warning or "death" in result.warning.lower()

    def test_causation_query_returns_warning(self, mock_engine):
        """Queries using 'cause' language must warn about FAERS association vs causation."""
        result = mock_engine.query("what drug causes the most reactions")
        assert result.warning is not None


# Cache key tests
class TestCacheKey:
    """Tests for cache key generation."""

    def test_cache_key_is_deterministic(self, mock_engine):
        """Same question must always produce the same cache key."""
        key1 = mock_engine._cache_key("aspirin adverse reactions")
        key2 = mock_engine._cache_key("aspirin adverse reactions")
        assert key1 == key2

    def test_different_questions_produce_different_keys(self, mock_engine):
        """Different questions must produce different cache keys."""
        key1 = mock_engine._cache_key("aspirin reactions")
        key2 = mock_engine._cache_key("warfarin reactions")
        assert key1 != key2

    def test_cache_key_format(self, mock_engine):
        """Cache key must follow the expected namespace format."""
        key = mock_engine._cache_key("test question")
        assert key.startswith("faers:query:")

    def test_cache_hit_returns_from_cache(self, mock_db, mock_redis_hit, mock_llm):
        """When Redis has a cached result, it must be returned without calling the LLM."""
        from nlp.query_engine import FAERSQueryEngine
        engine = FAERSQueryEngine(
            db_conn=mock_db,
            redis_client=mock_redis_hit,
            llm_client=mock_llm,
            enable_cache=True,
            explain_results=False,
        )
        result = engine.query("top drugs")
        assert result.from_cache is True
        # LLM must NOT have been called — we used the cache
        mock_llm.chat.completions.create.assert_not_called()


# QueryResult model tests
class TestQueryResult:
    """Tests for the QueryResult data structure."""

    def test_row_count_matches_data_length(self):
        result = QueryResult(
            question="test",
            sql="SELECT 1",
            columns=["col1"],
            data=[(1,), (2,), (3,)],
            explanation="test",
            response_time_ms=100,
        )
        assert result.row_count == 3

    def test_empty_data_gives_zero_row_count(self):
        result = QueryResult(
            question="test",
            sql="SELECT 1",
            columns=[],
            data=[],
            explanation="",
            response_time_ms=0,
        )
        assert result.row_count == 0
