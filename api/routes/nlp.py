"""
Natural Language Query endpoint for FAERS
"""


from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_db, get_llm, get_redis
from nlp.query_engine import FAERSQueryEngine

router = APIRouter()

class NLQueryRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        example="What are the top adverse reactions for ibuprofen?",
    )
    quarter: str | None = Field(
        None,
        example="2026q1",
        description="Filter results to a specific quarter (optional)",
    )

class NLQueryResponse(BaseModel):
    question: str
    sql: str
    columns: list
    data: list
    row_count: int
    explanation: str
    response_time_ms: int
    from_cache: bool
    query_type: str
    warning: str | None = None
    error: str | None = None

@router.post("/query", response_model=NLQueryResponse, summary="Natural language query")
async def nlp_query(
    request: NLQueryRequest,
    conn=Depends(get_db),
    cache=Depends(get_redis),
    llm=Depends(get_llm),
):
    """
    Convert a natural language question into SQL and execute it against FAERS data.
    
    **Examples:**
    - "What are the top adverse reactions for warfarin?"
    - "Which drugs have the most death reports in 2026 Q1?"
    - "Show me the safety signals for metformin"
    - "What is the age distribution of patients reporting reactions to ozempic?"
    - "Which countries report the most adverse events?"
    - "Compare death reports between aspirin and ibuprofen"
    
    **Response time target:** < 5 seconds
    """
    engine = FAERSQueryEngine(
        db_conn=conn,
        redis_client=cache,
        llm_client=llm,
    )

    result = engine.query(request.question, quarter_filter=request.quarter)

    if result.error:
        # Return 400 for validation errors, 408 for timeouts
        if "timeout" in result.error.lower():
            raise HTTPException(status_code=408, detail=result.error)
        if "validation" in result.error.lower() or "cannot" in result.error.lower():
            raise HTTPException(status_code=400, detail=result.error)

    return NLQueryResponse(**result.to_dict())

@router.get("/examples", summary="Example questions to try")
async def get_examples():
    """Return a list of example NL queries to help users get started."""
    return {
        "examples": [
            {
                "category": "Drug Reactions",
                "questions": [
                    "What are the top 20 adverse reactions for aspirin?",
                    "What side effects are most commonly reported with metformin?",
                    "Show all reactions linked to ozempic",
                ],
            },
            {
                "category": "Safety Signals",
                "questions": [
                    "Are there any safety signals for warfarin?",
                    "Show confirmed PRR signals for statins",
                    "Is there a signal between metformin and lactic acidosis?",
                ],
            },
            {
                "category": "Patient Outcomes",
                "questions": [
                    "Which drugs have the most death reports?",
                    "How many hospitalizations are linked to ibuprofen?",
                    "Show the breakdown of outcomes for chemotherapy drugs",
                ],
            },
            {
                "category": "Demographics",
                "questions": [
                    "What is the age distribution of patients reporting reactions to warfarin?",
                    "Are more men or women reporting adverse events for aspirin?",
                    "Show pediatric adverse events (under 18) for any vaccine",
                ],
            },
            {
                "category": "Geographic",
                "questions": [
                    "Which countries report the most adverse events?",
                    "How many reports came from India?",
                    "Compare US vs European reporting rates",
                ],
            },
            {
                "category": "Trends",
                "questions": [
                    "Show quarterly reporting trends over time",
                    "How has the number of death reports changed by quarter?",
                ],
            },
            {
                "category": "Comparisons",
                "questions": [
                    "Compare deaths between aspirin and ibuprofen",
                    "Which NSAID has the most adverse event reports?",
                    "Compare reactions for brand vs generic metformin",
                ],
            },
        ]
    }

@router.get("/history", summary="Recent query history")
async def query_history(
    limit: int = 20,
    conn=Depends(get_db),
):
    """
    View recent NL queries, their generated SQL, and response times.

    Returns the generated_sql field for every past query so analysts can
    audit the AI-generated SQL and detect hallucinations in historical queries.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT query_text, generated_sql, response_time_ms,
                   rows_returned, from_cache, error_message, created_at
            FROM nlq_query_log
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()

    return {
        "queries": [
            {
                "question":         r[0],
                "generated_sql":    r[1],          # ← SQL the AI produced
                "response_time_ms": r[2],
                "rows_returned":    r[3],
                "from_cache":       r[4],
                "error":            r[5],           # ← None if query succeeded
                "timestamp":        r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ]
    }
