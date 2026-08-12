"""
FastAPI dependency injection for DB, Redis, LLM connections

Uses connection pooling for performance under concurrent load.
"""

import os
from functools import lru_cache
from typing import Generator

import psycopg2
import psycopg2.pool
import redis
from openai import OpenAI
from dotenv import load_dotenv

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
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            _llm_client = OpenAI(
                api_key=api_key,
                base_url=os.getenv("OPENAI_BASE_URL"),
                timeout=20.0,
                max_retries=2,
            )
        except Exception:
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
