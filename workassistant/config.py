import os
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "workassistant")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "workassistant")

# Safely construct DATABASE_URL from separate variables
DATABASE_URL = f"postgresql+asyncpg://{quote_plus(POSTGRES_USER)}:{quote_plus(POSTGRES_PASSWORD)}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
PRIMARY_PROJECT_ROOT = os.getenv("PRIMARY_PROJECT_ROOT", "/mnt/c/RB/Workarea/Repo")
ADDITIONAL_PROJECT_ROOTS = os.getenv("ADDITIONAL_PROJECT_ROOTS", "").split(",") if os.getenv("ADDITIONAL_PROJECT_ROOTS") else []
AGENT_NAME = os.getenv("AGENT_NAME", "WorkAssistant")
AGENT_MODEL = os.getenv("AGENT_MODEL", "openai:gpt-4o")

# --- Enhanced scanning configuration ---

# File size limits
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "1"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_DIFF_SIZE_KB = int(os.getenv("MAX_DIFF_SIZE_KB", "50"))
MAX_DIFF_SIZE_BYTES = MAX_DIFF_SIZE_KB * 1024

# AI settings for commit summarisation
AI_SUMMARY_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
AI_MAX_OUTPUT_TOKENS = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "500"))
COMMIT_AGE_THRESHOLD_DAYS = int(os.getenv("COMMIT_AGE_THRESHOLD_DAYS", "365"))

# Parallel processing
SCAN_WORKERS = int(os.getenv("SCAN_WORKERS", "4"))

# Checkpoint persistence intervals
CHECKPOINT_SAVE_INTERVAL_SECONDS = int(os.getenv("CHECKPOINT_SAVE_INTERVAL_SECONDS", "120"))
CHECKPOINT_SAVE_INTERVAL_ITEMS = int(os.getenv("CHECKPOINT_SAVE_INTERVAL_ITEMS", "10"))

# Directory patterns to ignore during scanning
SCAN_IGNORE_PATTERNS = os.getenv(
    "SCAN_IGNORE_PATTERNS",
    ".git,node_modules,__pycache__,.venv,venv,dist,build,.tox,.eggs,*.egg-info"
).split(",")

# --- Graphify knowledge graph configuration ---
GRAPHIFY_OUTPUT_DIR = os.getenv("GRAPHIFY_OUTPUT_DIR", "data/graphs")
GRAPHIFY_AUTO_BUILD = os.getenv("GRAPHIFY_AUTO_BUILD", "false").lower() == "true"
GRAPHIFY_MAX_FILES = int(os.getenv("GRAPHIFY_MAX_FILES", "5000"))

# --- Logging configuration ---
LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# OpenAI pricing per 1M tokens (kept in sync with main.py PRICING dict)
AI_PRICING = {
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
}

# --- Chat context configuration ---
CHAT_CONTEXT_WINDOW_SIZE = int(os.getenv("CHAT_CONTEXT_WINDOW_SIZE", "10"))
