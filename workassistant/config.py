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
