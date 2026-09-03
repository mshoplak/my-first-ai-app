import logging
import os
import secrets
import time
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
        "arabic",
        "bengali",
        "chinese",
        "czech",
        "danish",
        "dutch",
        "english",
        "finnish",
        "french",
        "german",
        "greek",
        "hebrew",
        "hindi",
        "hungarian",
        "indonesian",
        "italian",
        "japanese",
        "korean",
        "malay",
        "norwegian",
        "polish",
        "portuguese",
        "romanian",
        "russian",
        "spanish",
        "swedish",
        "thai",
        "turkish",
        "ukrainian",
        "urdu",
        "vietnamese",
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
    if not secrets.compare_digest(header_token, GATEWAY_SECRET):
        raise HTTPException(status_code=403, detail="Invalid gateway credentials")
    _enforce_rate_limit(header_token)
    return header_token


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
        return {
            "resolved_by": "OpenAI (gpt-4o)",
            "transformed_text": content.strip(),
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
        return {
            "resolved_by": "Anthropic (Claude Sonnet 5)",
            "response_payload": "".join(text_parts),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail="Chat service unavailable")
