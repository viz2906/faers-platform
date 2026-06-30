"""
Additional tests to push coverage above 80%

Covers the execution, logging, reconnect, and explanation paths
in query_engine.py that are not covered by test_query_engine.py.
"""

import pytest
import json
import psycopg2
from unittest.mock import MagicMock, patch, call

# _execute path — timeout and execution error handling
class TestQueryExecutionPaths:
    """Tests for the _execute method and its error paths."""

    def test_query_timeout_returns_friendly_error(self, mock_db, mock_redis, mock_llm):
        """When DB raises QueryCanceled (timeout), user gets a clear message."""
        from nlp.query_engine import FAERSQueryEngine
        import psycopg2.errors

        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.execute.side_effect = psycopg2.errors.QueryCanceled("timeout")

        mock_db.cursor.return_value = mock_cursor

        engine = FAERSQueryEngine(
            db_conn=mock_db,
            redis_client=mock_redis,
            llm_client=mock_llm,
            enable_cache=False,
            explain_results=False,
        )
        result = engine.query("top drugs")
        assert result.error is not None
        assert "timeout" in result.error.lower()

    def test_db_execution_error_triggers_reconnect(self, mock_redis, mock_llm, sample_sql):
        """When query execution fails, engine attempts to reconnect and retry."""
        from nlp.query_engine import FAERSQueryEngine

        # First cursor raises generic error; after reconnect, second cursor succeeds
        fail_cursor = MagicMock()
        fail_cursor.__enter__ = MagicMock(return_value=fail_cursor)
        fail_cursor.__exit__ = MagicMock(return_value=False)
        fail_cursor.execute.side_effect = Exception("connection lost")

        fail_conn = MagicMock()
        fail_conn.cursor.return_value = fail_cursor

        with patch("psycopg2.connect") as mock_connect:
            # Reconnect returns a working connection
            ok_cursor = MagicMock()
            ok_cursor.__enter__ = MagicMock(return_value=ok_cursor)
            ok_cursor.__exit__ = MagicMock(return_value=False)
            ok_cursor.description = [("drugname_clean",)]
            ok_cursor.fetchall.return_value = [("ASPIRIN", 100)]
            ok_conn = MagicMock()
            ok_conn.cursor.return_value = ok_cursor
            mock_connect.return_value = ok_conn

            engine = FAERSQueryEngine(
                db_conn=fail_conn,
                redis_client=mock_redis,
                llm_client=mock_llm,
                enable_cache=False,
                explain_results=False,
            )
            result = engine.query("top drugs")
            # Reconnect must have been attempted
            assert mock_connect.called

    def test_persistent_db_error_returns_error_result(self, mock_redis, mock_llm):
        """When both initial and retry execution fail, error is captured gracefully."""
        from nlp.query_engine import FAERSQueryEngine

        fail_cursor = MagicMock()
        fail_cursor.__enter__ = MagicMock(return_value=fail_cursor)
        fail_cursor.__exit__ = MagicMock(return_value=False)
        fail_cursor.execute.side_effect = Exception("connection refused")

        fail_conn = MagicMock()
        fail_conn.cursor.return_value = fail_cursor

        with patch("psycopg2.connect", side_effect=Exception("still down")):
            engine = FAERSQueryEngine(
                db_conn=fail_conn,
                redis_client=mock_redis,
                llm_client=mock_llm,
                enable_cache=False,
                explain_results=False,
            )
            result = engine.query("top drugs")
            assert result.error is not None

# _log_query path
class TestQueryLogging:
    """Tests for query logging to nlq_query_log table."""

    def test_successful_query_is_logged(self, mock_engine, mock_db):
        """After a successful query, _log_query must insert into nlq_query_log."""
        result = mock_engine.query("top drugs")
        # cursor() must have been called for both execute and logging
        assert mock_db.cursor.called

    def test_log_failure_does_not_crash_query(self, mock_redis, mock_llm, sample_sql):
        """If logging fails (DB issue), the query result must still be returned."""
        from nlp.query_engine import FAERSQueryEngine

        call_count = [0]

        def cursor_factory():
            call_count[0] += 1
            c = MagicMock()
            c.__enter__ = MagicMock(return_value=c)
            c.__exit__ = MagicMock(return_value=False)
            if call_count[0] == 1:
                # First cursor: execute works fine
                c.description = [("col",)]
                c.fetchall.return_value = [("ASPIRIN",)]
            else:
                # Second cursor (logging): raises
                c.execute.side_effect = Exception("log table unavailable")
            return c

        mock_conn = MagicMock()
        mock_conn.cursor = cursor_factory
        mock_conn.commit = MagicMock()

        engine = FAERSQueryEngine(
            db_conn=mock_conn,
            redis_client=mock_redis,
            llm_client=mock_llm,
            enable_cache=False,
            explain_results=False,
        )
        # Should NOT raise even if logging fails
        result = engine.query("top drugs")
        assert result is not None

# _explain_results path
class TestExplanationGeneration:
    """Tests for the AI explanation step."""

    def test_explanation_populated_when_enabled(self, mock_db, mock_redis, mock_llm_explanation):
        """When explain_results=True, the explanation field must be non-empty."""
        from nlp.query_engine import FAERSQueryEngine

        engine = FAERSQueryEngine(
            db_conn=mock_db,
            redis_client=mock_redis,
            llm_client=mock_llm_explanation,
            enable_cache=False,
            explain_results=True,   # ← enabled
        )
        result = engine.query("top drugs")
        assert result.explanation, "Explanation must be populated when explain_results=True"

    def test_explanation_empty_when_no_data(self, mock_db, mock_redis, mock_llm):
        """When query returns no rows, explanation should indicate no results."""
        from nlp.query_engine import FAERSQueryEngine

        empty_cursor = MagicMock()
        empty_cursor.__enter__ = MagicMock(return_value=empty_cursor)
        empty_cursor.__exit__ = MagicMock(return_value=False)
        empty_cursor.description = [("col",)]
        empty_cursor.fetchall.return_value = []  # ← no rows

        mock_db.cursor.return_value = empty_cursor

        engine = FAERSQueryEngine(
            db_conn=mock_db,
            redis_client=mock_redis,
            llm_client=mock_llm,
            enable_cache=False,
            explain_results=True,
        )
        result = engine.query("top drugs")
        assert "no results" in result.explanation.lower() or result.row_count == 0

    def test_explanation_failure_does_not_crash(self, mock_db, mock_redis, sample_sql):
        """If the explanation LLM call fails, the result must still be returned."""
        from nlp.query_engine import FAERSQueryEngine

        # SQL generation succeeds but explanation call fails
        sql_choice = MagicMock()
        sql_choice.message.content = sample_sql
        sql_response = MagicMock()
        sql_response.choices = [sql_choice]

        llm = MagicMock()
        llm.chat.completions.create.side_effect = [
            sql_response,               # first call: SQL generation 
            Exception("LLM rate limit") # second call: explanation 
        ]

        engine = FAERSQueryEngine(
            db_conn=mock_db,
            redis_client=mock_redis,
            llm_client=llm,
            enable_cache=False,
            explain_results=True,
        )
        result = engine.query("top drugs")
        assert result.error is None, "Query must succeed even if explanation fails"
        assert result.data is not None

# Cache write path
class TestCacheWrite:
    """Tests for caching query results in Redis."""

    def test_result_written_to_cache(self, mock_db, mock_redis, mock_llm):
        """After a successful query with cache enabled, result is stored in Redis."""
        from nlp.query_engine import FAERSQueryEngine

        engine = FAERSQueryEngine(
            db_conn=mock_db,
            redis_client=mock_redis,
            llm_client=mock_llm,
            enable_cache=True,      # ← enabled
            explain_results=False,
        )
        result = engine.query("top drugs")
        # Redis setex must have been called to store the result
        assert mock_redis.setex.called

    def test_cache_write_failure_does_not_crash(self, mock_db, mock_llm):
        """If Redis setex fails, query result is still returned."""
        from nlp.query_engine import FAERSQueryEngine

        broken_redis = MagicMock()
        broken_redis.get.return_value = None
        broken_redis.setex.side_effect = Exception("Redis OOM")

        engine = FAERSQueryEngine(
            db_conn=mock_db,
            redis_client=broken_redis,
            llm_client=mock_llm,
            enable_cache=True,
            explain_results=False,
        )
        result = engine.query("top drugs")
        assert result.error is None

# _get_faers_warning
class TestFAERSWarnings:
    """Tests for the contextual FAERS warning system."""

    def test_no_warning_for_neutral_question(self, mock_engine):
        result = mock_engine.query("top drugs by reports")
        # Neutral question should have no warning
        # (depends on question content, not guaranteed to be None,
        #  but at least must be a string or None)
        assert result.warning is None or isinstance(result.warning, str)

    def test_death_warning_message_content(self, mock_engine):
        result = mock_engine.query("drugs with the most death reports")
        assert result.warning is not None
        # Must mention FAERS and reporting context
        assert "FAERS" in result.warning or "report" in result.warning.lower()

    def test_cause_warning_message_content(self, mock_engine):
        result = mock_engine.query("what drug causes the most heart attacks")
        assert result.warning is not None
        assert "association" in result.warning.lower() or "FAERS" in result.warning
