"""
Shared pytest fixtures for FAERS Analytics Platform tests

All mocks are defined here so individual test files can simply declare
them as function arguments (pytest dependency injection).

Usage in a test file:
    def test_something(mock_engine, sample_drug_rows):
        result = mock_engine.query("top drugs")
        assert result.sql
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Sample FAERS data fixtures (small, deterministic datasets)
@pytest.fixture
def sample_drug_rows():
    """10 rows mimicking faers_drug query results."""
    return [
        ("ASPIRIN", 48231),
        ("WARFARIN", 31450),
        ("METFORMIN", 28900),
        ("IBUPROFEN", 24100),
        ("LISINOPRIL", 19800),
        ("ATORVASTATIN", 17600),
        ("OZEMPIC", 15200),
        ("INSULIN", 14800),
        ("AMOXICILLIN", 12300),
        ("PREDNISONE", 11100),
    ]

@pytest.fixture
def sample_columns():
    return ["drugname_clean", "report_count"]

@pytest.fixture
def sample_sql():
    return (
        "SELECT drugname_clean, COUNT(*) AS report_count "
        "FROM faers_drug WHERE role_cod = 'PS' "
        "GROUP BY drugname_clean ORDER BY report_count DESC LIMIT 10"
    )

# Mock database connection
@pytest.fixture
def mock_db(sample_columns, sample_drug_rows):
    """
    Mock psycopg2 connection that returns deterministic FAERS data.
    Cursor context manager is fully simulated.
    """
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.description = [(col,) for col in sample_columns]
    mock_cursor.fetchall.return_value = sample_drug_rows

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.commit = MagicMock()
    return mock_conn

# Mock Redis client
@pytest.fixture
def mock_redis():
    """Mock Redis that always reports a cache miss (returns None)."""
    r = MagicMock()
    r.get.return_value = None          # no cached result
    r.setex.return_value = True
    r.ping.return_value = True
    return r

@pytest.fixture
def mock_redis_hit(sample_columns, sample_drug_rows, sample_sql):
    """Mock Redis that returns a cached result (cache hit scenario)."""
    import json
    cached = {
        "question": "top drugs",
        "sql": sample_sql,
        "columns": sample_columns,
        "data": [list(r) for r in sample_drug_rows],
        "row_count": len(sample_drug_rows),
        "explanation": "Cached result.",
        "response_time_ms": 12,
        "from_cache": True,
        "query_type": "materialized_view:mv_top_drugs",
        "warning": None,
        "error": None,
    }
    r = MagicMock()
    r.get.return_value = json.dumps(cached)
    r.setex.return_value = True
    r.ping.return_value = True
    return r

# Mock LLM (OpenAI)
@pytest.fixture
def mock_llm(sample_sql):
    """
    Mock OpenAI client that returns a deterministic SQL string.
    Prevents real API calls (and costs) during tests.
    """
    mock_choice = MagicMock()
    mock_choice.message.content = sample_sql

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    llm = MagicMock()
    llm.chat.completions.create.return_value = mock_response
    return llm

@pytest.fixture
def mock_llm_explanation(sample_sql):
    """LLM mock that returns SQL on first call and an explanation on second call."""
    sql_choice = MagicMock()
    sql_choice.message.content = sample_sql

    explain_choice = MagicMock()
    explain_choice.message.content = (
        "Aspirin has the highest number of adverse event reports (48,231), "
        "followed by warfarin (31,450). "
        "Note: FAERS reports association, not proven causation."
    )

    sql_response = MagicMock()
    sql_response.choices = [sql_choice]

    explain_response = MagicMock()
    explain_response.choices = [explain_choice]

    llm = MagicMock()
    llm.chat.completions.create.side_effect = [sql_response, explain_response]
    return llm

# Pre-built FAERSQueryEngine using all mocks
@pytest.fixture
def mock_engine(mock_db, mock_redis, mock_llm):
    """
    A fully-mocked FAERSQueryEngine instance.

    No real DB, Redis, or LLM connections are made.
    Use this in unit tests for the query engine logic.
    """
    from nlp.query_engine import FAERSQueryEngine
    return FAERSQueryEngine(
        db_conn=mock_db,
        redis_client=mock_redis,
        llm_client=mock_llm,
        timeout_seconds=5,
        enable_cache=False,      # disable caching for deterministic unit tests
        explain_results=False,   # disable explanation to keep tests fast
    )

# FastAPI test client
@pytest.fixture
def test_client(mock_db, mock_redis, mock_llm):
    """
    FastAPI TestClient with mocked dependencies injected.
    Use this for integration tests of API routes.
    """
    from api.main import app
    from api import dependencies

    # Patch the module-level connection pool / clients
    with patch.object(dependencies, "_db_pool") as mock_pool, \
         patch.object(dependencies, "_redis_client", mock_redis), \
         patch.object(dependencies, "_llm_client", mock_llm):

        mock_pool.getconn.return_value = mock_db
        mock_pool.putconn = MagicMock()

        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
