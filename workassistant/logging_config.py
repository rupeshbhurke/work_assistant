"""
Centralized logging configuration for WorkAssistant.
Logs to both console and rotating files in logs/ directory.
"""
import logging
import logging.handlers
import os
from pathlib import Path


def setup_logging(
    log_dir: str = "logs",
    log_level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB per file
    backup_count: int = 5,
) -> None:
    """
    Configure logging for the application.

    Args:
        log_dir: Directory to store log files
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        max_bytes: Maximum size of each log file before rotation
        backup_count: Number of backup log files to keep
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Console handler (colored output)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler for all logs (rotating)
    app_log_file = log_path / "workassistant.log"
    file_handler = logging.handlers.RotatingFileHandler(
        app_log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Separate error log file
    error_log_file = log_path / "errors.log"
    error_handler = logging.handlers.RotatingFileHandler(
        error_log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    root_logger.addHandler(error_handler)

    # Separate scan job log file
    scan_log_file = log_path / "scan_jobs.log"
    scan_handler = logging.handlers.RotatingFileHandler(
        scan_log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    scan_handler.setLevel(logging.INFO)
    scan_handler.setFormatter(file_formatter)
    # Create a specific logger for scan jobs
    scan_logger = logging.getLogger("workassistant.scanning")
    scan_logger.addHandler(scan_handler)
    scan_logger.propagate = True

    logging.info(f"Logging configured. Logs directory: {log_path.absolute()}")
    logging.info(f"Main log: {app_log_file}")
    logging.info(f"Error log: {error_log_file}")
    logging.info(f"Scan log: {scan_log_file}")


def get_recent_logs(log_file: str = "workassistant.log", lines: int = 100) -> list[str]:
    """
    Read the last N lines from a log file.

    Args:
        log_file: Name of the log file in logs/ directory
        lines: Number of lines to return

    Returns:
        List of log lines
    """
    log_path = Path("logs") / log_file
    if not log_path.exists():
        return [f"Log file not found: {log_path}"]

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
    except Exception as e:
        return [f"Error reading log file: {e}"]
