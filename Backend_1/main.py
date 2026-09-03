import logging
import os
import secrets
import time
import csv  # <-- Added for structural spreadsheet logging
from datetime import datetime  # <-- Added for human-readable calendar tracking timestamps
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

# Resolve .env from repo parent relative to this file (CWD-independent)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

# Establish local pathing layouts for our persistent text sheet records
_HISTORY_LOG_PATH = Path(__file__).resolve().parent / "history.csv"
_history_file_lock = Lock()  # Prevents overlapping multi-threaded write collisions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("expat-gateway")

APP_ENV = os.getenv("APP_ENV", "development").lower()
IS_PRODUCTION = APP_ENV in {"production", "prod"}

# ----------------------------------------------------
# SECURITY: required secrets (fail closed)
# ----------------------------------------------------
GATEWAY_SECRET = os.getenv("GATEWAY_SECRET_PASSPHRASE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

_missing = [
    name
    for name, value in (
        ("GATEWAY_SECRET_PASSPHRASE", GATEWAY_SECRET),
        ("OPENAI_API_KEY", OPENAI_API_KEY),
        ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    )
    if not value
]
if _missing:
    raise RuntimeError(
        f"Missing required environment variables: {', '.join(_missing)}. "
        "Refusing to start with insecure defaults."
    )

API_KEY_NAME = "X-Nomad-Gateway-Token"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

# Simple in-memory rate limit: max requests per token per window
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "30"))
RATE_LIMIT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = Lock()

ALLOWED_LANGUAGES = frozenset(
    {
        "arabic", "bengali", "chinese", "czech", "danish", "dutch", "english",
        "finnish", "french", "german", "greek", "hebrew", "hindi", "hungarian",
        "indonesian", "italian", "japanese", "korean", "malay", "norwegian",
        "polish", "portuguese", "romanian", "russian", "spanish", "swedish",
        "thai", "turkish", "ukrainian", "urdu", "vietnamese",
    }
)

def _enforce_rate_limit(token: str) -> None:
    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets[token]
        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SEC:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again later.",
            )
        bucket.append(now)

async def validate_gateway_token(header_token: str = Security(api_key_header)):
    """
    Firewall filter that automatically unlocks for you during local development, 
    but strictly enforces security when hosted live in production.
    """
    # If your master .env file says APP_ENV=development, bypass the lock for easy testing!
    if not IS_PRODUCTION:
        return "development_bypass_token"
        
    # Strict enforcement rules applied exclusively on the live production cloud
    if not secrets.compare_digest(header_token, GATEWAY_SECRET):
        raise HTTPException(status_code=403, detail="Invalid gateway credentials")
    _enforce_rate_limit(header_token)
    return header_token


def append_to_history_log(engine_name: str, task_type: str, user_input: str, ai_output: str) -> None:
    """
    Safely appends a structural transaction line entry directly into our local CSV log.
    """
    try:
        file_exists = _HISTORY_LOG_PATH.exists()
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with _history_file_lock:
            with open(_HISTORY_LOG_PATH, mode="a", newline="", encoding="utf-8") as csv_file:
                writer = csv.writer(csv_file)
                if not file_exists:
                    # Initialize headers if the history tracker file is brand new
                    writer.writerow(["Timestamp", "Engine Module", "Transaction Mode", "User Prompt / Input", "AI Output Response"])
                writer.writerow([timestamp_str, engine_name, task_type, user_input, ai_output])
    except Exception as log_err:
        logger.error(f"⚠️ Internal Request History Logging Failed: {str(log_err)}")

# ----------------------------------------------------
# Lifespan / client pools
# ----------------------------------------------------
gateway_state: dict = {}

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    logger.info("Initializing AI client pools")
    gateway_state["openai"] = AsyncOpenAI(api_key=OPENAI_API_KEY)
    gateway_state["anthropic"] = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    yield
    logger.info("Closing AI client connections")
    await gateway_state["openai"].close()
    await gateway_state["anthropic"].close()

_enable_docs = os.getenv("ENABLE_DOCS", "false" if IS_PRODUCTION else "true").lower() in {
    "1",
    "true",
    "yes",
}

app = FastAPI(
    title="Expat AI Advanced Enterprise Gateway",
    description="Multi-provider AI gateway for OpenAI and Anthropic.",
    version="2.1.0",
    lifespan=app_lifespan,
    docs_url="/docs" if _enable_docs else None,
    redoc_url="/redoc" if _enable_docs else None,
    openapi_url="/openapi.json" if _enable_docs else None,
)

_allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", API_KEY_NAME],
)

# ----------------------------------------------------
# Schemas
# ----------------------------------------------------
class TranslationRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    target_language: str = Field(..., min_length=2, max_length=32)

    @field_validator("target_language")
    @classmethod
    def language_must_be_allowed(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_LANGUAGES:
            raise ValueError(
                "Unsupported target_language. Use a common language name "
                "(e.g. spanish, french, japanese)."
            )
        return normalized

class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)

# ----------------------------------------------------
# Routes
# ----------------------------------------------------
@app.get("/health", tags=["Monitoring"])
async def system_health_check():
    return {"status": "healthy"}

@app.post(
    "/api/translate",
    tags=["OpenAI Core"],
    dependencies=[Depends(validate_gateway_token)],
)
async def optimized_translation(payload: TranslationRequest):
    try:
        client: AsyncOpenAI = gateway_state["openai"]
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate the user text into the target language. "
                        f"Target language: {payload.target_language}. "
                        "Return only the translation."
                    ),
                },
                {"role": "user", "content": payload.text},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        transformed_output = content.strip()
        
        # LOG RETRIEVAL ASSIGNMENT: Append this transaction data directly to storage sheets
        append_to_history_log("OpenAI (gpt-4o)", f"Translation ({payload.target_language})", payload.text, transformed_output)
        
        return {
            "resolved_by": "OpenAI (gpt-4o)",
            "transformed_text": transformed_output,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Translation request failed")
        raise HTTPException(status_code=500, detail="Translation service unavailable")

@app.post(
    "/api/claude/chat",
    tags=["Anthropic Core"],
    dependencies=[Depends(validate_gateway_token)],
)
async def optimized_claude_chat(payload: ChatRequest):
    try:
        client: AsyncAnthropic = gateway_state["anthropic"]
        response = await client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": payload.prompt}],
            system="You are an advanced software architect AI. Provide concise answers.",
        )
        text_parts = [
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ]
        resolved_response = "".join(text_parts)
        
        # LOG RETRIEVAL ASSIGNMENT: Append this transaction data directly to storage sheets
        append_to_history_log("Anthropic (Claude Sonnet 5)", "Architect Chat Prompt", payload.prompt, resolved_response)
        
        return {
            "resolved_by": "Anthropic (Claude Sonnet 5)",
            "response_payload": resolved_response,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail="Chat service unavailable")
