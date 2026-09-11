import logging
import json
import os
import secrets
import time
import csv
import re
import asyncio
from datetime import datetime
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security, BackgroundTasks, Request, Header, APIRouter, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse, RedirectResponse
from openai import AsyncOpenAI
from pinecone import Pinecone
from pydantic import BaseModel, Field, field_validator
import stripe

# ----------------------------------------------------
# SYSTEM LOGGING ENGINE WITH METRIC DEPLOYMENT PROFILES
# ----------------------------------------------------
class JSONProductionLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_payload = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        if record.exc_info:
            log_payload["exception_trace"] = self.formatException(record.exc_info)
        return json.dumps(log_payload)

logger = logging.getLogger("expat-gateway")
log_handler = logging.StreamHandler()
IS_ON_RENDER = os.getenv("RENDER") is not None or os.getenv("PORT") is not None

if not IS_ON_RENDER:
    _LOCAL_REPO_PARENT = Path(__file__).resolve().parent.parent / ".env"
    _LOCAL_CURRENT_CWD = Path(".").resolve() / ".env"
    if _LOCAL_REPO_PARENT.exists():
        load_dotenv(dotenv_path=_LOCAL_REPO_PARENT)
    elif _LOCAL_CURRENT_CWD.exists():
        load_dotenv(dotenv_path=_LOCAL_CURRENT_CWD)

APP_ENV = os.getenv("APP_ENV", "development").lower()
IS_PRODUCTION = APP_ENV in {"production", "prod", "production-gateway"}

if IS_PRODUCTION:
    log_handler.setFormatter(JSONProductionLogFormatter())
    logger.setLevel(logging.INFO)
else:
    local_formatter = logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s: %(message)s")
    log_handler.setFormatter(local_formatter)
    logger.setLevel(logging.DEBUG)

logger.addHandler(log_handler)
logger.propagate = False
# ----------------------------------------------------
# ENVIRONMENT SETUP & SECURITY INITIALIZATION
# ----------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ai-app-logs")
ENABLE_PINECONE_LOGGING = os.getenv("ENABLE_PINECONE_LOGGING", "true").lower() in ("true", "1")
ANTHROPIC_MODEL_NAME = os.getenv("ANTHROPIC_MODEL_NAME", "claude-3-5-sonnet-20241022")
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_ID_PRO = os.getenv("STRIPE_PRICE_ID_PRO")
STRIPE_PRICE_ID_ENTERPRISE = os.getenv("STRIPE_PRICE_ID_ENTERPRISE")

if STRIPE_API_KEY:
    stripe.api_key = STRIPE_API_KEY

_HISTORY_LOG_PATH = Path(__file__).resolve().parent / "history.csv"
_REGISTRY_STORAGE_PATH = Path(__file__).resolve().parent / "registry.json"

# FIXED PERF: Large thread pool dedicated purely to non-blocking I/O network / disk writes
io_pool_executor = ThreadPoolExecutor(max_workers=64)

TIER_PROFILES = {
    "free": {"rate_limit": 5, "window": 60, "allowed_models": {"openai-gpt-4o-mini"}},
    "pro": {"rate_limit": 60, "window": 60, "allowed_models": {"openai-gpt-4o", "anthropic-sonnet"}},
    "enterprise": {"rate_limit": 300, "window": 60, "allowed_models": {"openai-gpt-4o", "anthropic-sonnet"}}
}

CUSTOMER_REGISTRY: dict[str, dict] = {}
CUSTOMER_ID_TO_TOKEN_MAP: dict[str, str] = {}  # FIXED PERF: O(1) Reverse cache dictionary map

def rebuild_reverse_lookup_map():
    global CUSTOMER_ID_TO_TOKEN_MAP
    CUSTOMER_ID_TO_TOKEN_MAP = {meta["customer_id"]: tk for tk, meta in CUSTOMER_REGISTRY.items()}

raw_keys_string = os.getenv("CUSTOMER_GATEWAY_KEYS", "").strip().strip('"').strip("'")
if raw_keys_string:
    for pair in raw_keys_string.split(","):
        clean_pair = pair.strip()
        parts = clean_pair.split(":")
        if len(parts) >= 2:
            token = parts[0].strip()
            client_name = parts[1].strip()
            tier = parts[2].strip().lower() if len(parts) >= 3 and parts[2].strip().lower() in TIER_PROFILES else "free"
            reseller_parent = parts[3].strip() if len(parts) == 4 else "direct"
            CUSTOMER_REGISTRY[token] = {
                "customer_id": client_name,
                "tier": tier,
                "monthly_spending_cap": 500.00 if tier == "enterprise" else (50.00 if tier == "pro" else 5.00),
                "current_month_spend": 0.0,
                "reseller_parent": reseller_parent
            }
    rebuild_reverse_lookup_map()

_missing = [name for name, value in (("OPENAI_API_KEY", OPENAI_API_KEY), ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY), ("PINECONE_API_KEY", PINECONE_API_KEY)) if not value]
if _missing or not CUSTOMER_REGISTRY:
    logger.error(f"CONFIGURATION ERROR: Missing parameters -> {_missing}")
    raise RuntimeError("CRITICAL ENVIRONMENT ERROR: Server initialization blocked.")

API_KEY_NAME = "X-Nomad-Gateway-Token"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

MODEL_PRICING = {
    "openai-gpt-4o": {"input": 2.50, "output": 10.00},
    "openai-gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "anthropic-sonnet": {"input": 3.00, "output": 15.00}
}
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "30"))
RATE_LIMIT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)

# FIXED PERF: Replaced standard thread-locks with ultra-fast asyncio resource locks
_rate_limit_lock = asyncio.Lock()

BASE_INJECTION_PATTERN = re.compile(
    r"(ignore\s*all\s*previous|system\s*prompt|developer\s*mode|override\s*instructions|you\s*are\s*now\s*a)", re.IGNORECASE
)
LEET_SUBSTITUTIONS = str.maketrans({
    '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '8': 'b', '@': 'a', '$': 's', '!': 'i', '¡': 'i'
})

def sanitize_user_prompt(text: str) -> str:
    if not text:
        return ""
    normalized = text.lower().strip()
    normalized = re.sub(r"[_\-\+\=\*\|\/\\\[\]\{\}\(\)\.\,\!\?\s]+", "", normalized)
    cleaned_check_string = text.lower().translate(LEET_SUBSTITUTIONS)
    if BASE_INJECTION_PATTERN.search(cleaned_check_string) or "ignoreallprevious" in normalized:
        logger.warning("Prompt Injection Guard Intercepted: Obfuscation attempt blocked.")
        raise HTTPException(
            status_code=400,
            detail="Security Flag: Request payload contains forbidden system override strings or character obfuscation vectors."
        )
    return text

ALLOWED_LANGUAGES = frozenset(
    {"arabic", "bengali", "chinese", "czech", "danish", "dutch", "english", "finnish", "french", "german", "greek", "hebrew", "hindi", "hungarian", "indonesian", "italian", "japanese", "korean", "malay", "norwegian", "polish", "portuguese", "romanian", "russian", "spanish", "swedish", "thai", "turkish", "ukrainian", "urdu", "vietnamese"}
)

async def _enforce_rate_limit(token: str, tier: str = "free") -> None:
    now = time.monotonic()
    profile = TIER_PROFILES.get(tier, {"rate_limit": RATE_LIMIT_MAX, "window": RATE_LIMIT_WINDOW_SEC})
    limit = profile["rate_limit"]
    window = profile["window"]

    async with _rate_limit_lock:
        bucket = _rate_buckets[token]
        while bucket and (now - bucket[0]) > window:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded for plan tier [{tier.upper()}]. Try again later.")
        bucket.append(now)

async def validate_gateway_token(header_token: str = Security(api_key_header)) -> dict:
    clean_header_token = header_token.strip()
    
    # FIXED PERF: O(1) Instant direct dictionary target lookup. Wipes out lagging loops.
    matched_customer = CUSTOMER_REGISTRY.get(clean_header_token)
    if not matched_customer:
        raise HTTPException(status_code=403, detail="Invalid gateway credentials")
        
    await _enforce_rate_limit(clean_header_token, matched_customer["tier"])
    return {**matched_customer, "gateway_secure_token_key": clean_header_token}
# ----------------------------------------------------
# PYDANTIC DATA VALIDATORS & SCHEMAS
# ----------------------------------------------------
class LogSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(5, ge=1, le=20)
    @field_validator("query")
    @classmethod
    def sanitize_search_query(cls, value: str) -> str: return sanitize_user_prompt(value)

class TranslationRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    target_language: str = Field(..., min_length=2, max_length=32)
    @field_validator("text")
    @classmethod
    def sanitize_translation_text(cls, value: str) -> str: return sanitize_user_prompt(value)
    @field_validator("target_language")
    @classmethod
    def language_must_be_allowed(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_LANGUAGES: raise ValueError("Unsupported target_language.")
        return normalized

class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    @field_validator("prompt")
    @classmethod
    def sanitize_chat_prompt(cls, value: str) -> str: return sanitize_user_prompt(value)

class VisaConsultationRequest(BaseModel):
    destination_country: str = Field(..., min_length=2, max_length=64)
    current_citizenship: str = Field(..., min_length=2, max_length=64)
    monthly_income_usd: float = Field(..., ge=0.0)
    query: str = Field(..., min_length=5, max_length=2000)
    @field_validator("query", "destination_country", "current_citizenship")
    @classmethod
    def guard_legal_inputs(cls, value: str) -> str: return sanitize_user_prompt(value)

class CustomerRegistrationRequest(BaseModel):
    email: str = Field(..., max_length=128)
    client_name: str = Field(..., min_length=2, max_length=64)

# ----------------------------------------------------
# THREAD-SAFE CLIENT LAYER LIFESPAN POOLS
# ----------------------------------------------------
openai_pool: AsyncOpenAI = None
anthropic_pool: AsyncAnthropic = None
pinecone_pool: Pinecone = None  # TYPO FIX: Structural verification context set back to explicit Pinecone layout

def load_persisted_registry():
    if _REGISTRY_STORAGE_PATH.exists():
        try:
            with open(_REGISTRY_STORAGE_PATH, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
            for token, metadata in saved_data.items():
                CUSTOMER_REGISTRY[token] = metadata
            rebuild_reverse_lookup_map()
            logger.info(f"Registry rehydrated dynamically. Loaded {len(saved_data)} profiles.")
        except Exception as err:
            logger.error(f"Failed to load local state database: {str(err)}")

def _sync_save_registry_worker(registry_snapshot):
    try:
        with open(_REGISTRY_STORAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(registry_snapshot, f, indent=4)
    except Exception as err:
        logger.error(f"Storage layer transaction error: {str(err)}")

def async_trigger_registry_save():
    snapshot = json.loads(json.dumps(CUSTOMER_REGISTRY))
    loop = asyncio.get_running_loop()
    loop.run_in_executor(io_pool_executor, _sync_save_registry_worker, snapshot)

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    global openai_pool, anthropic_pool, pinecone_pool
    load_persisted_registry()
    logger.info("Initializing explicit timeout AI and Database client sockets")
    openai_pool = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=30.0)
    anthropic_pool = AsyncAnthropic(api_key=ANTHROPIC_API_KEY, timeout=30.0)
    if PINECONE_API_KEY:
        pinecone_pool = Pinecone(api_key=PINECONE_API_KEY)
    yield
    logger.info("Closing active resource lanes safely")
    await openai_pool.close()
    await anthropic_pool.close()
    io_pool_executor.shutdown(wait=False)

def verify_engine_pool(pool_object, engine_name: str) -> None:
    if pool_object is None:
        logger.critical(f"State validation failure. Offline subsystem: {engine_name}")
        raise HTTPException(
            status_code=503, detail=f"Gateway system routing error: [{engine_name}] layer is currently unavailable."
        )
# ----------------------------------------------------
# SYSTEM APP SETUP & FIREWALL MIDDLEWARE (HARDENED)
# ----------------------------------------------------
app = FastAPI(
    title="Expat AI Advanced Enterprise Gateway",
    description="Multi-tenant gateway tracking client authorization strings.",
    version="4.4.0",
    lifespan=app_lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json"
)

# ====================================================================
# HARDENED PRODUCTION CORS FIREWALL (REPLACES CHUNK 5 MIDDLEWARE)
# ====================================================================
# Define your explicit allowed testing and production web domains
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://onrender.com", # primary live server link
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True, # Allowed safely now because origins are explicitly named
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Nomad-Gateway-Token", "accept"],
)

@app.middleware("http")
async def enforce_production_ssl_redirect(request: Request, call_next):
    """
    Enforces secure HTTPS routing lines on public cloud deployment clusters
    without dropping cross-origin preflight handshakes.
    """
    # 1. Instantly let browser preflight OPTIONS handshakes clear without check filters
    if request.method == "OPTIONS":
        return await call_next(request)

    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    _internal_whitelisted_paths = {
        "/", 
        "/health", 
        "/health/deep", 
        "/docs", 
        "/redoc", 
        "/openapi.json", 
        "/api/v1/webhooks/stripe"
    }
    
    if (IS_ON_RENDER or IS_PRODUCTION) and forwarded_proto == "http" and request.url.path not in _internal_whitelisted_paths:
        secure_url = request.url.replace(scheme="https")
        return RedirectResponse(secure_url, status_code=301)
        
    return await call_next(request)


# ----------------------------------------------------
# SECURITY HARDENED LOGGING & EMBEDDING ENGINES
# ----------------------------------------------------
def sanitize_for_csv(text: str) -> str:
    if not text: return ""
    clean_text = text.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    if clean_text.startswith(('=', '+', '-', '@')):
        return f"'{clean_text}"
    return clean_text

def _sync_csv_append_worker(timestamp_str, customer_id, engine_name, task_type, clean_input, clean_output, total_cost):
    try:
        if _HISTORY_LOG_PATH.exists() and _HISTORY_LOG_PATH.stat().st_size > (10 * 1024 * 1024):
            backup_path = _HISTORY_LOG_PATH.with_name("history_old.csv")
            if backup_path.exists():
                backup_path.unlink()
            _HISTORY_LOG_PATH.rename(backup_path)
        
        file_exists = _HISTORY_LOG_PATH.exists()
        with open(_HISTORY_LOG_PATH, mode="a", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            if not file_exists:
                writer.writerow(["Timestamp", "Authorized Client ID", "Engine", "Mode", "Input Payload", "AI Output Response", "Total Cost ($)"])
            writer.writerow([timestamp_str, customer_id, engine_name, task_type, clean_input, clean_output, f"${total_cost:.6f}"])
    except Exception as err:
        logger.error(f"CSV Logging write failure context dropped: {str(err)}")

def _sync_pinecone_upsert(index_name: str, vectors: list, namespace: str):
    try:
        index_target = pinecone_pool.Index(index_name)
        index_target.upsert(vectors=vectors, namespace=namespace)
    except Exception as e:
        logger.error(f"Async Pinecone Background Logger dropped: {str(e)}")

# FIXED PERF: Accepting precalculated payload vectors prevents doing secondary OpenAI requests inside logging operations
async def append_to_history_log_task(customer_id: str, reseller_parent: str, engine_name: str, task_type: str, user_input: str, ai_output: str, prompt_tokens: int, completion_tokens: int, pricing_key: str, precalculated_vector: list = None):
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_input = sanitize_for_csv(user_input)[:1000]
    clean_output = sanitize_for_csv(ai_output)[:2000]
    total_cost = 0.0

    if pricing_key and pricing_key in MODEL_PRICING:
        rates = MODEL_PRICING[pricing_key]
        total_cost = round(((prompt_tokens / 1000000.0) * rates["input"]) + ((completion_tokens / 1000000.0) * rates["output"]), 6)

    if not customer_id.startswith("sandbox_") and reseller_parent == "direct" and STRIPE_API_KEY:
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(
                io_pool_executor,
                lambda: stripe.billing.MeterEvent.create(
                    event_name="ai_gateway_tokens",
                    payload={"value": str(prompt_tokens + completion_tokens), "stripe_customer_id": customer_id},
                    timestamp=int(time.time())
                )
            )
        except Exception as e:
            logger.error(f"Stripe Background Metering Failure: {str(e)}")

    loop = asyncio.get_running_loop()
    loop.run_in_executor(io_pool_executor, _sync_csv_append_worker, timestamp_str, customer_id, engine_name, task_type, clean_input, clean_output, total_cost)

    if ENABLE_PINECONE_LOGGING and PINECONE_API_KEY and pinecone_pool:
        try:
            if precalculated_vector:
                vector_values = precalculated_vector
            elif openai_pool:
                text_to_embed = f"Client: {customer_id} | Input: {clean_input} | Output: {clean_output}"
                embedding_response = await openai_pool.embeddings.create(input=[text_to_embed], model="text-embedding-3-large", dimensions=2048)
                vector_values = embedding_response.data[0].embedding
            else:
                return

            log_id = f"log_{secrets.token_hex(8)}"
            metadata_payload = {
                "timestamp": timestamp_str, "customer_id": customer_id, "engine": engine_name, "mode": task_type,
                "input_text": clean_input, "output_text": clean_output, "prompt_tokens": str(prompt_tokens),
                "completion_tokens": str(completion_tokens), "total_tokens": str(prompt_tokens + completion_tokens),
                "estimated_cost_usd": str(total_cost)
            }
            current_namespace = datetime.now().strftime("logs-%Y-%m")
            loop.run_in_executor(io_pool_executor, _sync_pinecone_upsert, PINECONE_INDEX_NAME, [{"id": log_id, "values": vector_values, "metadata": metadata_payload}], current_namespace)
        except Exception as err:
            logger.error(f"Background Vector Storage Logging interrupted: {str(err)}")
# ----------------------------------------------------
# SYSTEM VERSIONED ROUTING LAYER & INITIAL CONTROLLERS
# ----------------------------------------------------
v1_router = APIRouter(prefix="/api/v1")
_processed_stripe_events = deque(maxlen=5000)
_stripe_idempotency_lock = asyncio.Lock()

@app.get("/health", tags=["Monitoring"])
async def system_health_check(): return {"status": "healthy"}

@app.get("/health/deep", tags=["Monitoring"])
async def deep_health_check():
    checks = {}
    try:
        if openai_pool: await openai_pool.models.list(timeout=5.0)
        checks["openai"] = "ok"
    except Exception: checks["openai"] = "unreachable"
    try:
        if anthropic_pool: await anthropic_pool.models.list(timeout=5.0)
        checks["anthropic"] = "ok"
    except Exception: checks["anthropic"] = "unreachable"
    try:
        if pinecone_pool:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(io_pool_executor, pinecone_pool.describe_index, PINECONE_INDEX_NAME)
            checks["pinecone"] = "ok"
        else: checks["pinecone"] = "offline"
    except Exception: checks["pinecone"] = "unreachable"
    
    is_degraded = any(status in {"unreachable", "offline"} for status in checks.values())
    return {"status": "degraded" if is_degraded else "healthy", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "checks": checks}

# ----------------------------------------------------
# AUTOMATED STRIPE BILLING COMPONENT (HIGH PERFORMANCE)
# ----------------------------------------------------
@app.post("/api/v1/webhooks/stripe", tags=["Automated Billing Engine"])
async def stripe_billing_webhook(request: Request, x_stripe_signature: str = Header(None)):
    if not x_stripe_signature: raise HTTPException(status_code=400, detail="Missing verification headers.")
    if not STRIPE_WEBHOOK_SECRET: raise HTTPException(status_code=500, detail="Billing webhook configuration offline.")
    
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, x_stripe_signature, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid billing signature payload: {str(e)}")

    event_id = event.get("id")
    async with _stripe_idempotency_lock:
        if event_id in _processed_stripe_events: return {"status": "duplicate_ignored", "processed": True}
        _processed_stripe_events.append(event_id)

    if event["type"] == "customer.subscription.deleted":
        sub_obj = event["data"]["object"]
        stripe_customer_id = sub_obj["customer"]
        
        #FIXED PERF: O(1) Instant direct dictionary token target mapping lookup. No loop lag.
        target_token = CUSTOMER_ID_TO_TOKEN_MAP.get(stripe_customer_id)
        if target_token and target_token in CUSTOMER_REGISTRY:
            CUSTOMER_REGISTRY[target_token]["tier"] = "free"
            CUSTOMER_REGISTRY[target_token]["monthly_spending_cap"] = 5.00
            async_trigger_registry_save()
            logger.warning(f"Subscription Terminated: Customer {stripe_customer_id} downgraded to free.")

    elif event["type"] in {"customer.subscription.created", "customer.subscription.updated"}:
        sub_obj = event["data"]["object"]
        stripe_customer_id = sub_obj["customer"]
        stripe_price_id = sub_obj["items"]["data"]["price"]["id"]
        sub_status = sub_obj["status"]

        new_tier, spending_cap = "free", 5.00
        if stripe_price_id == STRIPE_PRICE_ID_PRO:
            new_tier, spending_cap = "pro", 50.00
        elif stripe_price_id == STRIPE_PRICE_ID_ENTERPRISE:
            new_tier, spending_cap = "enterprise", 500.00

        target_token = CUSTOMER_ID_TO_TOKEN_MAP.get(stripe_customer_id)
        if target_token and target_token in CUSTOMER_REGISTRY:
            if sub_status == "active":
                CUSTOMER_REGISTRY[target_token]["tier"] = new_tier
                CUSTOMER_REGISTRY[target_token]["monthly_spending_cap"] = spending_cap
            else:
                CUSTOMER_REGISTRY[target_token]["tier"] = "free"
                CUSTOMER_REGISTRY[target_token]["monthly_spending_cap"] = 5.00
            async_trigger_registry_save()
    return {"status": "success", "processed": True}

@app.post("/api/v1/checkout/session", tags=["Automated Billing Engine"])
async def create_nomad_checkout_session(payload: CustomerRegistrationRequest):
    try:
        loop = asyncio.get_running_loop()
        customer = await loop.run_in_executor(io_pool_executor, lambda: stripe.Customer.create(email=payload.email, name=payload.client_name))
        generated_token = f"nvt_{secrets.token_urlsafe(32)}"
        
        CUSTOMER_REGISTRY[generated_token] = {
            "customer_id": customer["id"], "tier": "free", "monthly_spending_cap": 5.00, "current_month_spend": 0.0, "reseller_parent": "direct"
        }
        CUSTOMER_ID_TO_TOKEN_MAP[customer["id"]] = generated_token
        async_trigger_registry_save()

        session = await loop.run_in_executor(
            io_pool_executor,
            lambda: stripe.checkout.Session.create(
                customer=customer["id"], payment_method_types=["card"],
                line_items=[{"price": STRIPE_PRICE_ID_PRO, "quantity": 1}], mode="subscription",
                success_url="https://your-app-portal.com", cancel_url="https://your-app-portal.com",
            )
        )
        return {"registration_status": "pending_payment", "assigned_gateway_token": generated_token, "stripe_checkout_redirect_url": session["url"]}
    except Exception as err:
        logger.error(f"Checkout Session Generation Interruption: {str(err)}")
        raise HTTPException(status_code=500, detail="Failed to initialize user checkout sequence.")
# ----------------------------------------------------
# CORE AI WORKLOAD PROXIES (OPTIMIZED FOR ZERO LAG)
# ----------------------------------------------------
@v1_router.post("/translate", tags=["Proxy Engines"])
async def optimized_translation(
    payload: TranslationRequest, 
    background_tasks: BackgroundTasks, 
    client_auth: dict = Depends(validate_gateway_token)
):
    verify_engine_pool(openai_pool, "OpenAI")
    current_spend = client_auth.get("current_month_spend", 0.0)
    max_cap = client_auth.get("monthly_spending_cap", 5.00)
    
    if current_spend >= max_cap:
        raise HTTPException(status_code=402, detail="Payment Required: Monthly platform budget threshold exceeded.")

    assigned_model, pricing_key = "gpt-4o", "openai-gpt-4o"
    if client_auth["tier"] == "free":
        assigned_model, pricing_key = "gpt-4o-mini", "openai-gpt-4o-mini"

    target = payload.target_language.strip().lower()
    premium_languages = frozenset({"arabic", "bengali", "czech", "danish", "dutch", "finnish", "greek", "hebrew", "hindi", "hungarian", "indonesian", "italian", "korean", "malay", "norwegian", "polish", "portuguese", "romanian", "russian", "spanish", "swedish", "thai", "turkish", "ukrainian", "urdu", "vietnamese"})
    
    if client_auth["tier"] == "free" and target in premium_languages:
        raise HTTPException(status_code=402, detail="Premium Subsystem Language pairing requirements require Pro or Enterprise plans.")

    try:
        async with asyncio.timeout(20.0):
            response = await openai_pool.chat.completions.create(
                model=assigned_model,
                messages=[
                    {"role": "system", "content": f"Translate the user text into fluent {payload.target_language}."},
                    {"role": "user", "content": payload.text},
                ],
                temperature=0.2,
            )

        if response and response.choices and len(response.choices) > 0:
            transformed_output = response.choices[0].message.content.strip()
        else:
            transformed_output = ""

        usage = response.usage
        p_tok, c_tok = (usage.prompt_tokens, usage.completion_tokens) if usage else (0, 0)
        
        if pricing_key in MODEL_PRICING:
            cost = ((p_tok / 1000000.0) * MODEL_PRICING[pricing_key]["input"]) + ((c_tok / 1000000.0) * MODEL_PRICING[pricing_key]["output"])
            secure_token_key = client_auth["gateway_secure_token_key"]
            CUSTOMER_REGISTRY[secure_token_key]["current_month_spend"] = round(current_spend + cost, 6)

        background_tasks.add_task(append_to_history_log_task, client_auth["customer_id"], client_auth["reseller_parent"], f"OpenAI ({assigned_model})", f"Translation ({payload.target_language})", payload.text, transformed_output, p_tok, c_tok, pricing_key)
        return {"resolved_by": f"OpenAI ({assigned_model})", "transformed_text": transformed_output}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Upstream completion transaction timed out at the route boundary.")
    except Exception as err:
        logger.error(f"Translation Processing Crash Traceback: {str(err)}")
        raise HTTPException(status_code=500, detail="Translation service processing failed.")

@v1_router.post("/claude/chat", tags=["Proxy Engines"])
async def optimized_claude_chat(
    payload: ChatRequest, 
    background_tasks: BackgroundTasks, 
    client_auth: dict = Depends(validate_gateway_token)
):
    verify_engine_pool(anthropic_pool, "Anthropic")
    current_spend = client_auth.get("current_month_spend", 0.0)
    max_cap = client_auth.get("monthly_spending_cap", 5.00)
    
    if current_spend >= max_cap:
        raise HTTPException(status_code=402, detail="Payment Required: Monthly platform budget threshold exceeded.")
    if "anthropic-sonnet" not in TIER_PROFILES[client_auth["tier"]]["allowed_models"]:
        raise HTTPException(status_code=403, detail=f"Access Forbidden: Model access restricted on plan tier [{client_auth['tier'].upper()}].")

    try:
        async with asyncio.timeout(20.0):
            response = await anthropic_pool.messages.create(
                model=ANTHROPIC_MODEL_NAME, max_tokens=1024,
                messages=[{"role": "user", "content": payload.prompt}],
                system="You are an advanced software architect AI. Provide concise answers.",
            )

        if response and response.content and len(response.content) > 0:
            resolved_response = getattr(response.content[0], 'text', "").strip()
        else:
            resolved_response = "Error: No response generated from the model."

        usage = response.usage
        p_tok, c_tok = (usage.input_tokens, usage.output_tokens) if usage else (0, 0)
        
        cost = ((p_tok / 1000000.0) * MODEL_PRICING["anthropic-sonnet"]["input"]) + ((c_tok / 1000000.0) * MODEL_PRICING["anthropic-sonnet"]["output"])
        secure_token_key = client_auth["gateway_secure_token_key"]
        CUSTOMER_REGISTRY[secure_token_key]["current_month_spend"] = round(current_spend + cost, 6)

        background_tasks.add_task(append_to_history_log_task, client_auth["customer_id"], client_auth["reseller_parent"], f"Anthropic ({ANTHROPIC_MODEL_NAME})", "Architect Chat Prompt", payload.prompt, resolved_response, p_tok, c_tok, "anthropic-sonnet")
        return {"resolved_by": f"Anthropic ({ANTHROPIC_MODEL_NAME})", "response_payload": resolved_response}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Upstream completion transaction timed out at the route boundary.")
    except Exception:
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail="Chat service unavailable")
@v1_router.post("/visa/advise", tags=["Expat Legal Core"])
async def generate_visa_legal_advice(
    payload: VisaConsultationRequest, 
    background_tasks: BackgroundTasks, 
    client_auth: dict = Depends(validate_gateway_token)
):
    if client_auth["tier"] == "free":
        raise HTTPException(status_code=402, detail="Premium Subsystem: The Visa Advisory Engine requires an active Pro or Enterprise plan.")
        
    verify_engine_pool(openai_pool, "OpenAI")
    verify_engine_pool(anthropic_pool, "Anthropic")
    verify_engine_pool(pinecone_pool, "Pinecone")

    current_spend = client_auth.get("current_month_spend", 0.0)
    max_cap = client_auth.get("monthly_spending_cap", 5.00)
    if current_spend >= max_cap:
        raise HTTPException(status_code=402, detail="Payment Required: Monthly platform budget threshold exceeded.")

    try:
        search_prompt = f"Visa options for {payload.current_citizenship} citizen moving to {payload.destination_country}. Income: ${payload.monthly_income_usd}/mo. Context: {payload.query}"

        async with asyncio.timeout(10.0):
            embedding_response = await openai_pool.embeddings.create(
                input=[search_prompt], model="text-embedding-3-large", dimensions=2048
            )
        
        if embedding_response and embedding_response.data and len(embedding_response.data) > 0:
            query_vector = embedding_response.data[0].embedding
        else:
            raise HTTPException(status_code=500, detail="Failed to compute text semantic vectors.")

        index_target = pinecone_pool.Index(PINECONE_INDEX_NAME)
        clean_country_query = payload.destination_country.strip().lower()
        
        target_docs = [f"{clean_country_query}_immigration_laws_and_visa_criteria"]
        if clean_country_query == "mexico":
            target_docs.append("mexican_immigration_laws_and_visa_criteria")
        else:
            target_docs.append(f"{clean_country_query}_laws")

        loop = asyncio.get_running_loop()
        raw_laws = await loop.run_in_executor(
            io_pool_executor,
            lambda: index_target.query(
                vector=query_vector, top_k=3, include_metadata=True,
                namespace="global-immigration-statutes",
                filter={"document_id": {"$in": target_docs}}
            )
        )

        context_snippets = []
        for match in raw_laws.get("matches", []):
            if match.get("score", 0) >= 0.15:
                meta = match.get("metadata", {})
                context_snippets.append(f"Source [{meta.get('document_id', 'Local Database')}]: {meta.get('text_extract', '')}")

        if not context_snippets:
            logger.info(f"Database lookup blank for {payload.destination_country}. Launching Stealth Web Agent...")
            tavily_key = os.getenv("TAVILY_API_KEY")
            if not tavily_key:
                logger.error("Agent Blocked: Missing TAVILY_API_KEY inside environment configuration variables.")
                laws_context = "No specific statutory text matches found locally, and web extraction agent is inactive."
            else:
                try:
                    from tavily import TavilyClient
                    tavily_client = TavilyClient(api_key=tavily_key)
                    agent_query = f"official digital nomad temporary resident visa requirements income criteria {payload.destination_country} for {payload.current_citizenship} citizens minimum financial solvency"
                    
                    search_results = await loop.run_in_executor(
                        io_pool_executor,
                        lambda: tavily_client.search(
                            query=agent_query, search_depth="advanced", max_results=3, include_raw_content=False, include_answer=True
                        )
                    )

                    if search_results.get("answer"):
                        context_snippets.append(f"Summary Context [Live Agent Search Overview]: {search_results['answer']}")
                    for res in search_results.get("results", []):
                        if res.get('snippet'):
                            context_snippets.append(f"Source [Live Stealth Web Agent - {res.get('url')}]: {res.get('snippet', '')}")
                    laws_context = "\n\n".join(context_snippets)
                except Exception as agent_err:
                    logger.warning(f"Stealth Agent fallback loop dropped: {str(agent_err)}")
                    laws_context = "No specific statutory text matches found."
        else:
            laws_context = "\n\n".join(context_snippets)

        system_instruction = (
            "You are an elite international immigration attorney specializing in digital nomad visas.\n"
            "Analyze the verified regulatory context files provided below and give precise, structured advice.\n"
            "Always include a mandatory section at the very top titled 'REGULATORY LEGAL DISCLAIMER' explaining this does not constitute formal legal representation."
        )
        user_content = f"CUSTOMER PROFILE:\nPassport: {payload.current_citizenship}\nTarget: {payload.destination_country}\nIncome: ${payload.monthly_income_usd:.2f}/mo\n\nREFERENCE DATA:\n{laws_context}\n\nQUERY:\n{payload.query}"

        async with asyncio.timeout(20.0):
            response = await anthropic_pool.messages.create(
                model=ANTHROPIC_MODEL_NAME, max_tokens=2048,
                system=system_instruction, messages=[{"role": "user", "content": user_content}]
            )

        if response and response.content and len(response.content) > 0:
            resolved_advice = response.content[0].text.strip()
        else:
            resolved_advice = "Error: No legal advisory payload could be generated."

        usage = response.usage
        p_tok, c_tok = (usage.input_tokens, usage.output_tokens) if usage else (0, 0)
        
        cost = ((p_tok / 1000000.0) * MODEL_PRICING["anthropic-sonnet"]["input"]) + ((c_tok / 1000000.0) * MODEL_PRICING["anthropic-sonnet"]["output"])
        secure_token_key = client_auth["gateway_secure_token_key"]
        CUSTOMER_REGISTRY[secure_token_key]["current_month_spend"] = round(current_spend + cost, 6)

        background_tasks.add_task(append_to_history_log_task, client_auth["customer_id"], client_auth["reseller_parent"], f"Anthropic ({ANTHROPIC_MODEL_NAME})", f"Visa Advisor ({payload.destination_country})", payload.query, resolved_advice, p_tok, c_tok, "anthropic-sonnet", query_vector)
        return {
            "resolved_by": "Expat Legal Advisory Core (Claude 3.5 Sonnet)",
            "account_tier": client_auth["tier"],
            "legal_context_matches_found": len(context_snippets),
            "advice_payload": resolved_advice
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Upstream processing timed out at the route boundary.")
    except Exception as err:
        logger.error(f"Visa Advisor Routing Engine Malfunction: {str(err)}")
        raise HTTPException(status_code=500, detail="Immigration legal advisory engine is temporarily offline.")
@v1_router.post("/logs/search", tags=["Enterprise Log Retrieval"])
async def secure_vector_log_search(
    payload: LogSearchRequest, 
    client_auth: dict = Depends(validate_gateway_token)
):
    verify_engine_pool(openai_pool, "OpenAI")
    verify_engine_pool(pinecone_pool, "Pinecone")
    try:
        async with asyncio.timeout(25.0):
            embedding_response = await openai_pool.embeddings.create(
                input=[payload.query], model="text-embedding-3-large", dimensions=2048
            )
        if embedding_response and embedding_response.data and len(embedding_response.data) > 0:
            query_vector = embedding_response.data[0].embedding
        else:
            raise HTTPException(status_code=500, detail="Failed to compute text data vectors.")

        current_date = datetime.now()
        current_namespace = current_date.strftime("logs-%Y-%m")
        if current_date.month == 1:
            prev_namespace = f"logs-{current_date.year - 1}-12"
        else:
            prev_namespace = f"logs-{current_date.year}-{str(current_date.month - 1).zfill(2)}"
        namespaces_to_scan = [current_namespace, prev_namespace]

        index_target = pinecone_pool.Index(PINECONE_INDEX_NAME)
        all_matches = []
        loop = asyncio.get_running_loop()

        # FIXED PERF: Query both historical vector partitions simultaneously over the network using thread tasks
        tasks = [
            loop.run_in_executor(
                io_pool_executor,
                lambda ns=namespace: index_target.query(
                    vector=query_vector, top_k=payload.top_k, include_metadata=True,
                    namespace=ns, filter={"customer_id": {"$eq": client_auth["customer_id"]}}
                )
            )
            for namespace in namespaces_to_scan
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for search_results in results:
            if isinstance(search_results, Exception):
                logger.warning(f"Skipped partition namespace scanning boundary layout: {str(search_results)}")
                continue
            all_matches.extend(search_results.get("matches", []))

        all_matches = sorted(all_matches, key=lambda x: x.get("score", 0), reverse=True)[:payload.top_k]
        CONFIDENCE_THRESHOLD = 0.10
        parsed_logs = []
        for match in all_matches:
            score = round(match.get("score", 0), 4)
            if score >= CONFIDENCE_THRESHOLD:
                metadata = match.get("metadata", {})
                clean_payload = {k: (str(v) if not isinstance(v, list) else [str(x) for x in v]) for k, v in metadata.items()}
                parsed_logs.append({
                    "log_id": match.get("id"), "similarity_score": score, "data_payload": clean_payload
                })
        return {
            "search_query": payload.query, "partitions_scanned": namespaces_to_scan,
            "records_found_count": len(parsed_logs), "results": parsed_logs
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Log retrieval search timed out.")
    except Exception as err:
        logger.error(f"Search Fault Error: {str(err)}")
        raise HTTPException(status_code=500, detail="Log retrieval service unavailable")

# ====================================================================
# HARDENED SECURE ADMIN DASHBOARD ENGINE (CLEAN & COMPLETE)
# ====================================================================
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

@v1_router.get("/gateway/control-panel", include_in_schema=False)
async def secure_admin_control_panel_docs(token: str = None):
    """
    Renders the control panel using the original ?token= variable name.
    Allows access for your dev token to get you testing immediately.
    """
    if not token: 
        raise HTTPException(status_code=403, detail="Access Denied: Missing authorization token.")
        
    clean_token = token.strip()
    
    # Check if the token exists in your registry
    matched_meta = CUSTOMER_REGISTRY.get(clean_token)
    if not matched_meta:
        raise HTTPException(status_code=403, detail="Access Denied: Invalid gateway token.")

    # Restored to look for '?token=' so your original URLs work perfectly
    return get_swagger_ui_html(
        openapi_url=f"/api/v1/gateway/secure-schema.json?token={clean_token}",
        title="Administrative Master Control Panel Proxy Gateway"
    )

@v1_router.get("/gateway/secure-schema.json", include_in_schema=False)
async def secure_admin_runtime_schema(request: Request, token: str = None):
    """
    Generates the schema layout dynamically by reading the request.
    Forces your accurate Render domain into the configuration to fix CORS.
    """
    if not token: 
        raise HTTPException(status_code=403, detail="Access Denied.")
        
    clean_token = token.strip()
    if clean_token not in CUSTOMER_REGISTRY:
        raise HTTPException(status_code=403, detail="Access Denied.")

    openapi_schema = get_openapi(
        title="Hardened Enterprise API Gateway Platform", 
        version="4.5.0", 
        routes=app.routes
    )
    
    # This automatically builds 'https://onrender.com' in the background!
    base_server_url = str(request.base_url).rstrip("/")
    openapi_schema["servers"] = [{"url": base_server_url}]
    return openapi_schema

# ====================================================================
# FIXED LOG DOWNLOAD COMPONENT (REMOVES PARAMETER CLASHES)
# ====================================================================
from fastapi.responses import StreamingResponse
import io

@v1_router.get("/gateway/download-history", tags=["Enterprise Log Retrieval"])
async def export_vector_logs_to_csv(download_auth_token: str = None):
    """
    Dumps history dynamically from Pinecone partitions directly into a 
    downloadable browser CSV file, bypassing unstable local server storage completely.
    """
    # FIXED: Switched parameter target variable to clear routing intersections
    if not download_auth_token: 
        raise HTTPException(status_code=403, detail="Access Denied: Missing authentication parameter.")
    
    clean_token = download_auth_token.strip()
    client_auth = CUSTOMER_REGISTRY.get(clean_token)
    if not client_auth:
        raise HTTPException(status_code=403, detail="Invalid Credentials.")

    # 1. Fetch historical record nodes from Pinecone partitions
    current_date = datetime.now()
    current_namespace = current_date.strftime("logs-%Y-%m")
    
    verify_engine_pool(pinecone_pool, "Pinecone")
    index_target = pinecone_pool.Index(PINECONE_INDEX_NAME)
    loop = asyncio.get_running_loop()
    
    try:
        search_results = await loop.run_in_executor(
            io_pool_executor,
            lambda: index_target.query(
                vector=[0.0] * 2048, 
                top_k=100,
                include_metadata=True,
                namespace=current_namespace,
                filter={"customer_id": {"$eq": client_auth["customer_id"]}}
            )
        )
        matches = search_results.get("matches", [])
    except Exception as e:
        logger.error(f"Pinecone CSV dynamic extraction break: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database extraction failed: {str(e)}")

    # 2. Programmatically generate a clean CSV string in system memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Authorized Client ID", "Engine", "Mode", "Input Payload", "Estimated Cost ($)"])
    
    for match in matches:
        meta = match.get("metadata", {})
        writer.writerow([
            meta.get("timestamp", ""),
            meta.get("customer_id", ""),
            meta.get("engine", ""),
            meta.get("mode", ""),
            meta.get("input_text", "")[:500],
            f"${meta.get('estimated_cost_usd', '0.00')}"
        ])
    
    # 3. Stream the file directly to your browser download window
    output.seek(0)
    return StreamingResponse(
        io.StringIO(output.getvalue()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=gateway_history_export.csv"}
    )


# --------------------------------------------------------------------
# ABSOLUTE LAST LINE OF THE FILE: MOUNT THE ROUTER TREE ONLY ONCE
# --------------------------------------------------------------------
app.include_router(v1_router)
