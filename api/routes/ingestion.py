import time
import os
import signal
import psutil
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, HTTPException
from typing import Dict, Any, List

from ingestion.quarterly_pipeline import run_pipeline

router = APIRouter(prefix="/ingestion", tags=["Ingestion"])

MAX_LOG_LINES = 200

# Simple in-memory state tracker for ingestion jobs
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
    "log": [],  # live log lines
}

def _add_log(message: str):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    ingestion_status["log"].append(f"[{ts}] {message}")
    # Keep log from growing unbounded
    if len(ingestion_status["log"]) > MAX_LOG_LINES:
        ingestion_status["log"] = ingestion_status["log"][-MAX_LOG_LINES:]

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

    _add_log(f"Pipeline started for quarter: {quarter.upper()}")

    def status_callback(stage: str, detail: str, progress: int = 0):
        ingestion_status["stage"] = stage
        ingestion_status["detail"] = detail
        ingestion_status["progress"] = progress
        _add_log(f"[{stage}] {detail}")

    try:
        stats = run_pipeline(
            quarter=quarter,
            force=False,
            download=True,
            skip_views=False,
            status_callback=status_callback
        )

        if ingestion_status["status"] == "running":
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

    except Exception as e:
        if ingestion_status["status"] == "running":
            ingestion_status["status"] = "error"
            ingestion_status["error"] = str(e)
            ingestion_status["end_time"] = time.time()
            _add_log(f"ERROR: {str(e)}")

@router.post("/load/{quarter}")
async def start_ingestion(quarter: str, background_tasks: BackgroundTasks):
    global ingestion_status
    if ingestion_status["status"] == "running":
        raise HTTPException(status_code=400, detail="An ingestion job is already running.")

    quarter = quarter.lower().strip()
    background_tasks.add_task(load_data_background, quarter)
    return {"message": f"Ingestion started for {quarter}", "status": "running"}

@router.post("/stop")
async def stop_ingestion():
    global ingestion_status
    if ingestion_status["status"] == "running":
        ingestion_status["status"] = "stopped"
        ingestion_status["error"] = "Stopped by user"
        ingestion_status["end_time"] = time.time()
        _add_log("Pipeline stopped by user.")

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
    return ingestion_status
