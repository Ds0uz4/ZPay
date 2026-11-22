"""Runtime configuration, read from environment / .env (LM Studio connection lives here)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(os.environ.get("ZPAY_WORKSPACE_ROOT") or Path(__file__).resolve().parent.parent)
load_dotenv(ROOT / ".env")


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or "").strip() or default


PORT = int(_env("PORT", "8000"))
LM_BASE_URL = _env("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
LM_API_KEY = _env("LM_STUDIO_API_KEY", "lm-studio")
LM_MODEL = _env("LM_STUDIO_MODEL", "qwen/qwen3-4b-2507")
LM_TEMPERATURE = float(_env("LM_STUDIO_TEMPERATURE", "0.2"))
LM_MAX_TOKENS = int(_env("LM_STUDIO_MAX_TOKENS", "4096"))
LM_TIMEOUT = float(_env("LM_STUDIO_TIMEOUT_S", "600"))

DOCS_DIR = ROOT / _env("RAG_DOCS_DIR", "docs/ingested")
RAG_TOP_K = int(_env("RAG_TOP_K", "6"))
ARTIFACTS_DIR = ROOT / _env("ARTIFACTS_DIR", "artifacts")
WEB_DIR = ROOT / "web"
