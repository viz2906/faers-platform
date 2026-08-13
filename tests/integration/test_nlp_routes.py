"""
Integration tests for the NLP/NLQ API routes

Tests the FastAPI routes using a TestClient with mocked dependencies.
No real DB, Redis, or OpenAI calls are made.
"""


class TestNLPQueryEndpoint:
    """Tests for POST /api/v1/nlp/query"""

    def test_valid_question_returns_200(self, test_client):
        resp = test_client.post(
            "/api/v1/nlp/query",
            json={"question": "What are the top drugs by adverse event reports?"},
        )
        assert resp.status_code == 200

    def test_response_contains_sql_field(self, test_client):
        """
        The sql field must be present and non-empty in every response.
        This is the hallucination-auditing requirement.
        """
        resp = test_client.post(
            "/api/v1/nlp/query",
            json={"question": "top adverse reactions for warfarin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sql" in data, "sql field must always be in the response"
        assert data["sql"], "sql field must not be empty"

    def test_response_has_expected_schema(self, test_client):
        """Every field in the NLQueryResponse model must be present."""
        resp = test_client.post(
            "/api/v1/nlp/query",
            json={"question": "top drugs by adverse events"},
        )
        assert resp.status_code == 200
        data = resp.json()
        required_fields = {
            "question", "sql", "columns", "data",
            "row_count", "explanation", "response_time_ms",
            "from_cache", "query_type",
        }
        missing = required_fields - data.keys()
        assert not missing, f"Response missing fields: {missing}"

    def test_question_too_short_returns_422(self, test_client):
        """Question shorter than min_length=5 must be rejected by Pydantic."""
        resp = test_client.post(
            "/api/v1/nlp/query",
            json={"question": "hi"},
        )
        assert resp.status_code == 422

    def test_empty_question_returns_422(self, test_client):
        resp = test_client.post(
            "/api/v1/nlp/query",
            json={"question": ""},
        )
        assert resp.status_code == 422

    def test_question_too_long_returns_422(self, test_client):
        """Question longer than max_length=1000 must be rejected."""
        resp = test_client.post(
            "/api/v1/nlp/query",
            json={"question": "a" * 1001},
        )
        assert resp.status_code == 422

    def test_missing_question_field_returns_422(self, test_client):
        resp = test_client.post("/api/v1/nlp/query", json={})
        assert resp.status_code == 422

    def test_with_quarter_filter(self, test_client):
        """Quarter filter should be accepted and forwarded to the engine."""
        resp = test_client.post(
            "/api/v1/nlp/query",
            json={
                "question": "top drugs by adverse events",
                "quarter": "2026q1",
            },
        )
        assert resp.status_code == 200

    def test_row_count_matches_data_length(self, test_client):
        resp = test_client.post(
            "/api/v1/nlp/query",
            json={"question": "top drugs by adverse events"},
        )
        data = resp.json()
        assert data["row_count"] == len(data["data"])

class TestNLPExamplesEndpoint:
    """Tests for GET /api/v1/nlp/examples"""

    def test_returns_200(self, test_client):
        resp = test_client.get("/api/v1/nlp/examples")
        assert resp.status_code == 200

    def test_returns_examples_list(self, test_client):
        resp = test_client.get("/api/v1/nlp/examples")
        data = resp.json()
        assert "examples" in data
        assert len(data["examples"]) > 0

    def test_each_example_has_category_and_questions(self, test_client):
        resp = test_client.get("/api/v1/nlp/examples")
        for example in resp.json()["examples"]:
            assert "category" in example
            assert "questions" in example
            assert len(example["questions"]) > 0

class TestNLPHistoryEndpoint:
    """Tests for GET /api/v1/nlp/history"""

    def test_returns_200(self, test_client):
        resp = test_client.get("/api/v1/nlp/history")
        assert resp.status_code == 200

    def test_response_has_queries_key(self, test_client):
        resp = test_client.get("/api/v1/nlp/history")
        data = resp.json()
        assert "queries" in data

    def test_history_includes_generated_sql(self, test_client):
        """
        The history endpoint must return generated_sql for each past query.
        This enables retrospective hallucination auditing.
        """
        resp = test_client.get("/api/v1/nlp/history")
        data = resp.json()
        # If there are queries, each must include generated_sql
        for query_record in data["queries"]:
            assert "generated_sql" in query_record, (
                "generated_sql must be returned in history for audit purposes"
            )

class TestHealthEndpoint:
    """Tests for GET /health"""

    def test_health_returns_200(self, test_client):
        resp = test_client.get("/health")
        assert resp.status_code == 200

    def test_health_has_status_field(self, test_client):
        resp = test_client.get("/health")
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded")
