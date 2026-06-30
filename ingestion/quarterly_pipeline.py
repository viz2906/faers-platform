"""
Full FAERS quarter ingestion orchestrator

Usage:
    python ingestion/quarterly_pipeline.py --quarter 2026q1
    python ingestion/quarterly_pipeline.py --quarter 2026q1 --force
    python ingestion/quarterly_pipeline.py --quarter 2026q1 --download-only
    python ingestion/quarterly_pipeline.py --all-available   # Download + load all quarters
"""

import os
import sys
import subprocess
import argparse
import time
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich import print as rprint

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.parse_faers import parse_quarter
from ingestion.load_to_db import load_quarter

console = Console()

# All available quarters (latest first)
AVAILABLE_QUARTERS = [
    "2026q1", "2025q4", "2025q3", "2025q2", "2025q1",
    "2024q4", "2024q3", "2024q2", "2024q1",
    "2023q4", "2023q3", "2023q2", "2023q1",
    "2022q4", "2022q3", "2022q2", "2022q1",
]

def download_quarter(quarter: str, data_dir: str = "./data/raw") -> bool:
    """Download a quarter using the shell script."""
    script = Path(__file__).parent.parent / "scripts" / "download.sh"
    if not script.exists():
        logger.error(f"Download script not found: {script}")
        return False
    
    env = os.environ.copy()
    env["FAERS_DATA_DIR"] = data_dir
    
    result = subprocess.run(
        ["bash", str(script), quarter],
        env=env,
        capture_output=False,
    )
    return result.returncode == 0

def run_pipeline(
    quarter: str,
    data_dir: str = "./data/raw",
    force: bool = False,
    download: bool = True,
    skip_views: bool = False,
    status_callback = None,
) -> dict:
    """Run the full pipeline for a single quarter."""
    
    def update_status(stage, detail="", progress=0):
        if status_callback:
            status_callback(stage, detail, progress)
    
    start_time = time.time()
    console.rule(f"[bold blue]FAERS Pipeline: {quarter.upper()}")
    
    # Step 1: Download
    if download:
        ascii_dir = Path(data_dir) / quarter / "ascii"
        if ascii_dir.exists() and not force:
            update_status("Downloading", "Data already downloaded, skipping...", 5)
            console.print(f"[yellow]Data already downloaded:[/yellow] {ascii_dir}")
        else:
            update_status("Downloading", f"Downloading zip from FDA for {quarter}...", 2)
            console.print(f"[cyan]Downloading {quarter}...[/cyan]")
            success = download_quarter(quarter, data_dir)
            if not success:
                update_status("Error", "Download failed.", 0)
                console.print(f"[red]Download failed for {quarter}[/red]")
                return {}
    
    # Step 2: Parse
    update_status("Parsing", "Parsing ASCII files into database format...", 10)
    ascii_dir = str(Path(data_dir) / quarter / "ascii")
    
    console.print(f"\n[cyan]Step 2/3: Parsing ASCII files...[/cyan]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress_cli:
        task = progress_cli.add_task("Parsing FAERS tables...", total=None)
        tables = parse_quarter(ascii_dir, quarter, status_callback)
        progress_cli.update(task, completed=True)
    
    if not tables:
        console.print(f"[red]Parse failed — no tables returned[/red]")
        return {}
    
    # Step 3: Load to DB
    update_status("Loading", "Bulk loading parsed data into PostgreSQL...", 40)
    console.print(f"\n[cyan]Step 3/3: Loading to PostgreSQL...[/cyan]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress_cli:
        task = progress_cli.add_task("Bulk loading tables...", total=None)
        stats = load_quarter(tables, quarter, force=force, skip_views=skip_views, status_callback=status_callback)
        progress_cli.update(task, completed=True)
    
    # Summary
    elapsed = time.time() - start_time
    
    table = Table(title=f"Load Summary — {quarter.upper()}", show_header=True)
    table.add_column("Table", style="cyan")
    table.add_column("Rows Loaded", justify="right", style="green")
    
    total = 0
    for tbl, rows in stats.items():
        table.add_row(tbl, f"{rows:,}")
        total += rows
    table.add_row("[bold]TOTAL", f"[bold]{total:,}")
    
    console.print(table)
    console.print(f"\n[bold green] Pipeline complete in {elapsed:.1f}s[/bold green]")
    
    return stats

def main():
    parser = argparse.ArgumentParser(description="FAERS Quarterly Data Pipeline")
    parser.add_argument("--quarter", type=str, default="2026q1",
                        help="Quarter to process (e.g. 2026q1)")
    parser.add_argument("--force", action="store_true",
                        help="Force re-download and re-load even if data exists")
    parser.add_argument("--download-only", action="store_true",
                        help="Only download, skip parsing and loading")
    parser.add_argument("--no-download", action="store_true",
                        help="Skip download, parse and load only")
    parser.add_argument("--skip-views", action="store_true",
                        help="Skip refreshing materialized views (faster for batch loads)")
    parser.add_argument("--data-dir", type=str, default="./data/raw",
                        help="Directory to store raw data")
    parser.add_argument("--all-available", action="store_true",
                        help="Process all available quarters")
    
    args = parser.parse_args()
    
    if args.all_available:
        console.print(f"[bold yellow]Processing all {len(AVAILABLE_QUARTERS)} available quarters[/bold yellow]")
        all_stats = {}
        for q in AVAILABLE_QUARTERS:
            try:
                stats = run_pipeline(
                    quarter=q,
                    data_dir=args.data_dir,
                    force=args.force,
                    download=not args.no_download,
                    skip_views=True,  # Refresh once at end
                )
                all_stats[q] = stats
            except Exception as e:
                console.print(f"[red]Failed {q}: {e}[/red]")
        
        # Final view refresh after all quarters
        console.print("\n[cyan]Refreshing materialized views (final pass)...[/cyan]")
        from ingestion.load_to_db import get_connection, refresh_materialized_views
        conn = get_connection()
        refresh_materialized_views(conn)
        conn.close()
    
    elif args.download_only:
        download_quarter(args.quarter, args.data_dir)
    
    else:
        run_pipeline(
            quarter=args.quarter,
            data_dir=args.data_dir,
            force=args.force,
            download=not args.no_download,
            skip_views=args.skip_views,
        )

if __name__ == "__main__":
    main()
