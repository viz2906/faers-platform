import time
import os
import signal
import psutil
import json
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from typing import Dict, Any, List

from ingestion.quarterly_pipeline import run_pipeline
from api.dependencies import get_redis, get_db

router = APIRouter(prefix="/ingestion", tags=["Ingestion"])

MAX_LOG_LINES = 200
REDIS_KEY = "faers_ingestion_status"

# In-memory fallback
ingestion_status: Dict[str, Any] = {
    "status": "idle",  # idle, running, completed, error, stopped
    "quarter": None,
    "start_time": None,
    "end_time": None,
    "error": None,
    "stats": None,
    "stage": None,
    "detail": None,
    "progress": 0,
    "log": [],
}

def _save_status():
    """Save ingestion status to Redis so all workers/containers stay in sync."""
    r = get_redis()
    if r:
        try:
            r.set(REDIS_KEY, json.dumps(ingestion_status))
        except Exception:
            pass

def get_current_status() -> Dict[str, Any]:
    """Retrieve shared ingestion status from Redis, falling back to local state."""
    r = get_redis()
    if r:
        try:
            data = r.get(REDIS_KEY)
            if data:
                return json.loads(data)
        except Exception:
            pass
    return ingestion_status

def _add_log(message: str):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    ingestion_status["log"].append(f"[{ts}] {message}")
    if len(ingestion_status["log"]) > MAX_LOG_LINES:
        ingestion_status["log"] = ingestion_status["log"][-MAX_LOG_LINES:]
    _save_status()

def load_data_background(quarter: str):
    global ingestion_status
    ingestion_status["status"] = "running"
    ingestion_status["quarter"] = quarter
    ingestion_status["start_time"] = time.time()
    ingestion_status["end_time"] = None
    ingestion_status["error"] = None
    ingestion_status["stats"] = None
    ingestion_status["stage"] = "Initializing"
    ingestion_status["detail"] = "Starting pipeline..."
    ingestion_status["progress"] = 0
    ingestion_status["log"] = []
    _save_status()

    _add_log(f"Pipeline started for quarter: {quarter.upper()}")

    def status_callback(stage: str, detail: str, progress: int = 0):
        ingestion_status["stage"] = stage
        ingestion_status["detail"] = detail
        ingestion_status["progress"] = progress
        _add_log(f"[{stage}] {detail}")
        _save_status()

    try:
        stats = run_pipeline(
            quarter=quarter,
            force=False,
            download=True,
            skip_views=False,
            status_callback=status_callback
        )

        current = get_current_status()
        if current.get("status") == "running":
            ingestion_status["status"] = "completed"
            ingestion_status["stats"] = stats
            ingestion_status["end_time"] = time.time()
            ingestion_status["progress"] = 100

            elapsed = time.time() - ingestion_status["start_time"]
            total_rows = sum(stats.values()) if stats else 0
            _add_log(f"Pipeline complete in {elapsed:.1f}s")
            if stats:
                for table, rows in stats.items():
                    _add_log(f"  {table}: {rows:,} rows loaded")
                _add_log(f"  TOTAL: {total_rows:,} rows across {len(stats)} tables")
            _save_status()

    except Exception as e:
        current = get_current_status()
        if current.get("status") == "running":
            ingestion_status["status"] = "error"
            ingestion_status["error"] = str(e)
            ingestion_status["end_time"] = time.time()
            _add_log(f"ERROR: {str(e)}")
            _save_status()

@router.post("/load/{quarter}")
async def start_ingestion(quarter: str, background_tasks: BackgroundTasks):
    global ingestion_status
    current = get_current_status()
    if current.get("status") == "running":
        raise HTTPException(status_code=400, detail="An ingestion job is already running.")

    quarter = quarter.lower().strip()
    background_tasks.add_task(load_data_background, quarter)
    ingestion_status["status"] = "running"
    ingestion_status["quarter"] = quarter
    ingestion_status["start_time"] = time.time()
    ingestion_status["stage"] = "Initializing"
    ingestion_status["detail"] = "Starting background worker..."
    ingestion_status["progress"] = 1
    _save_status()

    return {"message": f"Ingestion started for {quarter}", "status": "running"}

@router.post("/stop")
async def stop_ingestion():
    global ingestion_status
    current = get_current_status()
    if current.get("status") == "running":
        ingestion_status["status"] = "stopped"
        ingestion_status["error"] = "Stopped by user"
        ingestion_status["end_time"] = time.time()
        _add_log("Pipeline stopped by user.")
        _save_status()

        # Kill running subprocesses related to FAERS download/parsing
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmd = proc.info.get('cmdline')
                if cmd:
                    cmd_str = " ".join(cmd)
                    if "scripts/download.sh" in cmd_str or "ingestion/quarterly_pipeline.py" in cmd_str:
                        os.kill(proc.info['pid'], signal.SIGTERM)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return {"message": "Ingestion stopped"}
    return {"message": "No ingestion running"}

@router.get("/status")
async def get_ingestion_status():
    return get_current_status()

@router.post("/setup-schema", summary="Apply database schema to a fresh RDS instance")
async def setup_schema(conn=Depends(get_db)):
    """
    Apply schema.sql and materialized_views.sql to the connected PostgreSQL database.
    Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS / CREATE MATERIALIZED VIEW IF NOT EXISTS.
    Call this once after provisioning a new RDS instance before loading data.
    """
    from pathlib import Path
    base = Path(__file__).parent.parent.parent / "database"
    results = {}

    for fname in ["schema.sql", "materialized_views.sql"]:
        sql_file = base / fname
        if not sql_file.exists():
            results[fname] = "NOT FOUND"
            continue
        sql = sql_file.read_text(encoding="utf-8")
        try:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = 0;")
                cur.execute(sql)
            conn.commit()
            results[fname] = "applied"
        except Exception as e:
            conn.rollback()
            results[fname] = f"ERROR: {e}"

    return {"status": "done", "files": results}
