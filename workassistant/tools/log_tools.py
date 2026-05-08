from typing import Dict
from workassistant.logging_config import get_recent_logs


async def get_logs(log_file: str = "workassistant.log", lines: int = 50) -> Dict:
    """
    Get the most recent log lines from a log file.

    Args:
        log_file: Name of the log file in logs/ directory (e.g., workassistant.log, errors.log, scan_jobs.log)
        lines: Number of recent lines to retrieve (default: 50)

    Returns:
        Dictionary with log lines and metadata
    """
    log_lines = get_recent_logs(log_file, lines)
    return {
        "log_file": log_file,
        "lines_requested": lines,
        "lines_returned": len(log_lines),
        "logs": log_lines,
    }


async def get_available_log_files() -> Dict:
    """
    List all available log files in the logs/ directory.

    Returns:
        Dictionary with list of log files and their sizes
    """
    from pathlib import Path
    import os

    log_dir = Path("logs")
    if not log_dir.exists():
        return {"error": "logs/ directory does not exist"}

    files = []
    for f in log_dir.glob("*.log"):
        try:
            size = f.stat().st_size
            files.append({
                "name": f.name,
                "size_bytes": size,
                "size_human": f"{size:,} bytes" if size < 1024 * 1024 else f"{size / 1024 / 1024:.2f} MB"
            })
        except:
            pass

    return {
        "log_directory": str(log_dir.absolute()),
        "files": sorted(files, key=lambda x: x["name"]),
    }
