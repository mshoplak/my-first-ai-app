import logging
import os
import secrets
import time
import csv
from datetime import datetime
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from fastapi.responses import HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html  # <-- Added to customize UI layers
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

# ----------------------------------------------------
# 🌍 HIGH-RESILIENCE ENVIRONMENT INITIALIZATION
# ----------------------------------------------------
IS_ON_RENDER = os.getenv("RENDER") is not None or os.getenv("PORT") is not None

if not IS_ON_RENDER:
    _LOCAL_REPO_PARENT = Path(__file__).resolve().parent.parent / ".env"
    _LOCAL_CURRENT_CWD = Path(".").resolve() / ".env"
    
    if _LOCAL_REPO_PARENT.exists():
        load_dotenv(dotenv_path=_LOCAL_REPO_PARENT)
    elif _LOCAL_CURRENT_CWD.exists():
        load_dotenv(dotenv_path=_LOCAL_CURRENT_CWD)

APP_ENV = os.getenv("APP_ENV", "development").lower()
IS_PRODUCTION = APP_ENV in {"production", "prod"}

# ----------------------------------------------------
# 🔒 KEY CONFIGURATIONS & TELEMETRY SETUPS
# ----------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

_HISTORY_LOG_PATH = Path(__file__).resolve().parent / "history.csv"
_history_file_lock = Lock()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("expat-gateway")

CUSTOMER_KEYS: dict[str, str] = {}
raw_keys_string = os.getenv("CUSTOMER_GATEWAY_KEYS", "").strip().strip('"').strip("'")

if raw_keys_string:
    for pair in raw_keys_string.split(","):
        clean_pair = pair.strip()
        if ":" in clean_pair:
            token, client_name = clean_pair.split(":", 1)
            CUSTOMER_KEYS[token.strip()] = client_name.strip()

_missing = [
    name for name, value in (
        ("OPENAI_API_KEY", OPENAI_API_KEY),
        ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    ) if not value
]

if _missing or not CUSTOMER_KEYS:
    raise RuntimeError("CRITICAL SECURITY BLOCK: Environment variables verification failure.")

API_KEY_NAME = "X-Nomad-Gateway-Token"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

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
        while bucket and now - bucket > RATE_LIMIT_WINDOW_SEC:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
        bucket.append(now)

async def validate_gateway_token(header_token: str = Security(api_key_header)):
    matched_customer = None
    for secure_token, customer_id in CUSTOMER_KEYS.items():
        if secrets.compare_digest(header_token, secure_token):
            matched_customer = customer_id
            break
    if not matched_customer:
        raise HTTPException(status_code=403, detail="Invalid gateway credentials")
    _enforce_rate_limit(header_token)
    return matched_customer

def sanitize_for_csv(text: str) -> str:
    if not text:
        return ""
    if text.startswith(('=', '+', '-', '@')):
        return f"'{text}"
    return text

def append_to_history_log(customer_id: str, engine_name: str, task_type: str, user_input: str, ai_output: str) -> None:
    if os.getenv("ENABLE_HISTORY_LOGGING", "false").lower() not in ("true", "1"):
        return
    try:
        if _HISTORY_LOG_PATH.exists() and _HISTORY_LOG_PATH.stat().st_size > 10 * 1024 * 1024:
            return
        file_exists = _HISTORY_LOG_PATH.exists()
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _history_file_lock:
            with open(_HISTORY_LOG_PATH, mode="a", newline="", encoding="utf-8") as csv_file:
                writer = csv.writer(csv_file)
                if not file_exists:
                    writer.writerow(["Timestamp", "Authorized Client ID", "Engine", "Mode", "Input Payload", "AI Output Response"])
                writer.writerow([timestamp_str, customer_id, engine_name, task_type, sanitize_for_csv(user_input)[:1000], sanitize_for_csv(ai_output)[:2000]])
    except Exception as log_err:
        logger.error(f"⚠️ Request Logging Fault: {str(log_err)}")

# ----------------------------------------------------
# Lifespan Connection Pools
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

# Turn off native docs so we can inject our custom styled router below
app = FastAPI(
    title="Expat AI Advanced Enterprise Gateway",
    description="Multi-tenant provider AI gateway tracking individual client authorization strings.",
    version="2.3.0",
    lifespan=app_lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json"
)

# ----------------------------------------------------
# 🎨 CUSTOM MODERN PREMIUM DARK CYBER THEME INJECTION
# ----------------------------------------------------
_enable_docs = os.getenv("ENABLE_DOCS", "false" if IS_PRODUCTION else "true").lower() in {"1", "true", "yes"}

# FIXED: Added response_class=HTMLResponse parameter straight to the route gate
@app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
async def custom_swagger_ui_html():
    if not _enable_docs:
        raise HTTPException(status_code=404, detail="Not Found")
        
    custom_css = """
    body { background-color: #0d1117 !important; color: #c9d1d9 !important; font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif !important; }
    .swagger-ui .topbar { display: none !important; }
    .swagger-ui .info .title { color: #f0f6fc !important; font-weight: 700 !important; }
    .swagger-ui .info p, .swagger-ui .info li, .swagger-ui .info td { color: #8b949e !important; }
    .swagger-ui .scheme-container { background: #161b22 !important; box-shadow: none !important; border: 1px solid #30363d !important; border-radius: 8px !important; margin: 20px 0 !important; }
    .swagger-ui .opblock { border-radius: 8px !important; box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important; border: 1px solid #30363d !important; background: #161b22 !important; }
    .swagger-ui .opblock .opblock-summary { border-bottom: 1px solid rgba(255,255,255,0.05) !important; }
    .swagger-ui .opblock .opblock-summary-title { color: #f0f6fc !important; }
    .swagger-ui .opblock-description-wrapper p, .swagger-ui .opblock-external-docs-wrapper p, .swagger-ui .opblock-title_normal p { color: #8b949e !important; }
    .swagger-ui .tabli button { color: #c9d1d9 !important; font-weight: 600 !important; }
    .swagger-ui label { color: #8b949e !important; }
    .swagger-ui input[type=text], .swagger-ui textarea { background-color: #0d1117 !important; color: #58a6ff !important; border: 1px solid #30363d !important; border-radius: 6px !important; padding: 10px !important; font-weight: 600 !important; font-family: monospace !important; caret-color: #ff7b72 !important; }
    .swagger-ui input[type=text]:focus, .swagger-ui textarea:focus { border-color: #58a6ff !important; box-shadow: 0 0 0 3px rgba(88,166,255,0.3) !important; outline: none !important; }
    .swagger-ui .btn { background: #21262d !important; color: #c9d1d9 !important; border: 1px solid #30363d !important; border-radius: 6px !important; box-shadow: none !important; transition: all 0.2s !important; }
    .swagger-ui .btn:hover { background: #30363d !important; color: #f0f6fc !important; border-color: #8b949e !important; }
    .swagger-ui .btn.execute { background: #238636 !important; color: #ffffff !important; border-color: #2ea44f !important; font-weight: 700 !important; }
    .swagger-ui .btn.execute:hover { background: #2ea44f !important; }
    .swagger-ui .btn.authorize { background: transparent !important; color: #388bfd !important; border-color: #388bfd !important; }
    .swagger-ui .btn.authorize svg { fill: #388bfd !important; }
    .swagger-ui .btn.authorize:hover { background: rgba(56,139,253,0.1) !important; }
    .swagger-ui th { color: #f0f6fc !important; border-bottom: 2px solid #30363d !important; }
    .swagger-ui td { color: #c9d1d9 !important; }
    .swagger-ui .response-col_status { color: #58a6ff !important; font-weight: 700 !important; }
    .swagger-ui pre { background: #0d1117 !important; border: 1px solid #30363d !important; border-radius: 6px !important; color: #ff7b72 !important; }
    .swagger-ui pre.microlight { background: #0d1117 !important; }
    .swagger-ui pre code { color: #79c0ff !important; }
    .swagger-ui .opblock.opblock-post { background: #161b22 !important; border-color: #388bfd !important; }
    .swagger-ui .opblock.opblock-post .opblock-summary { background: rgba(56,139,253,0.05) !important; }
    .swagger-ui .opblock.opblock-post .opblock-summary-method { background: #388bfd !important; color: #ffffff !important; border-radius: 4px !important; }
    .swagger-ui .opblock.opblock-get { background: #161b22 !important; border-color: #3f6e51 !important; }
    .swagger-ui .opblock.opblock-get .opblock-summary { background: rgba(46,164,79,0.05) !important; }
    .swagger-ui .opblock.opblock-get .opblock-summary-method { background: #2ea44f !important; color: #ffffff !important; border-radius: 4px !important; }
    .swagger-ui .modal-ux { background-color: #161b22 !important; border: 1px solid #30363d !important; border-radius: 12px !important; box-shadow: 0 20px 40px rgba(0,0,0,0.5) !important; }
    .swagger-ui .modal-ux-header .modal-ux-header-title h3 { color: #f0f6fc !important; }
    .swagger-ui .modal-ux-content h4 { color: #8b949e !important; }
    """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <link rel="stylesheet" type="text/css" href="https://jsdelivr.net">
    <title>Expat AI Advanced Enterprise Gateway - Premium Dark</title>
    <style>{custom_css}</style>
    </head>
    <body>
    <div id="swagger-ui"></div>
    <script src="https://jsdelivr.net"></script>
    <script>
        const ui = SwaggerUIBundle({{
            url: '/openapi.json',
            dom_id: '#swagger-ui',
            presets: [
                SwaggerUIBundle.presets.apis
            ],
            layout: "BaseLayout",
            deepLinking: true,
            showExtensions: true,
            showCommonExtensions: true
        }});
    </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)