"""
FastAPI dependency injection for DB, Redis, LLM connections

Uses connection pooling for performance under concurrent load.
"""

import os

import psycopg2
import psycopg2.pool
import redis
from dotenv import load_dotenv
from loguru import logger
from openai import OpenAI

load_dotenv()

# Connection Pool (created once at startup)
_db_pool: psycopg2.pool.ThreadedConnectionPool = None
_redis_client: redis.Redis = None
_llm_client: OpenAI = None

def init_db_pool():
    global _db_pool
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=database_url,
            connect_timeout=10,
            options="-c timezone=UTC",
        )
    else:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            database=os.getenv("POSTGRES_DB", "faers"),
            user=os.getenv("POSTGRES_USER", "faers_user"),
            password=os.getenv("POSTGRES_PASSWORD", "faers_secret_pw"),
            connect_timeout=10,
            options="-c timezone=UTC",
        )

def init_redis():
    global _redis_client
    try:
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            _redis_client = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=2,
                socket_connect_timeout=2,
            )
        else:
            _redis_client = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                db=int(os.getenv("REDIS_DB", 0)),
                decode_responses=True,
                socket_timeout=2,
                socket_connect_timeout=2,
            )
        _redis_client.ping()
    except Exception:
        _redis_client = None

def init_llm():
    global _llm_client
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    
    if api_key and not base_url:
        if api_key.startswith("AIza") or api_key.startswith("AQ.") or os.getenv("GEMINI_API_KEY"):
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        elif api_key.startswith("gsk_"):
            base_url = "https://api.groq.com/openai/v1"

    if api_key:
        try:
            _llm_client = OpenAI(
                api_key=api_key,
                base_url=base_url if base_url else None,
                timeout=20.0,
                max_retries=2,
            )
        except Exception as e:
            logger.warning(f"Failed to initialize LLM client: {e}")
            _llm_client = None
    else:
        _llm_client = None

def get_db():
    """FastAPI dependency: get a DB connection from pool."""
    conn = _db_pool.getconn()
    try:
        yield conn
    finally:
        _db_pool.putconn(conn)

def get_redis():
    return _redis_client

def get_llm():
    return _llm_client
