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
from threading import Lock as ThreadingLock

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security, BackgroundTasks, Request, Header, APIRouter
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
_history_file_lock = ThreadingLock()
_history_async_lock = asyncio.Lock()

TIER_PROFILES = {
    "free": {"rate_limit": 5, "window": 60, "allowed_models": {"openai-gpt-4o-mini"}},
    "pro": {"rate_limit": 60, "window": 60, "allowed_models": {"openai-gpt-4o", "anthropic-sonnet"}},
    "enterprise": {"rate_limit": 300, "window": 60, "allowed_models": {"openai-gpt-4o", "anthropic-sonnet"}}
}


CUSTOMER_REGISTRY: dict[str, dict] = {}
raw_keys_string = os.getenv("CUSTOMER_GATEWAY_KEYS", "").strip().strip('"').strip("'")
if raw_keys_string:
    for pair in raw_keys_string.split(","):
        clean_pair = pair.strip()
        parts = clean_pair.split(":")
        # Fix active: extracts array variables by index positioning instead of stripping lists
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
_rate_lock = ThreadingLock()

# CHARACTER NORMALIZATION AND PROMPT INJECTION FILTER LAYER
BASE_INJECTION_PATTERN = re.compile(
    r"(ignore\s*all\s*previous|system\s*prompt|developer\s*mode|override\s*instructions|you\s*are\s*now\s*a)",
    re.IGNORECASE
)

LEET_SUBSTITUTIONS = str.maketrans({
    '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '8': 'b',
    '@': 'a', '$': 's', '!': 'i', '¡': 'i'
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

def _enforce_rate_limit(token: str, tier: str = "free") -> None:
    now = time.monotonic()
    profile = TIER_PROFILES.get(tier, {"rate_limit": RATE_LIMIT_MAX, "window": RATE_LIMIT_WINDOW_SEC})
    limit = profile["rate_limit"]
    window = profile["window"]
    
    with _rate_lock:
        dead_keys = [k for k, v in _rate_buckets.items() if not v or (now - v[-1]) > window]
        for dk in dead_keys:
            del _rate_buckets[dk]
            
        bucket = _rate_buckets[token]
        while bucket and (now - bucket) > window:
            bucket.popleft()
            
        if len(bucket) >= limit:
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded for plan tier [{tier.upper()}]. Try again later.")
        bucket.append(now)

async def validate_gateway_token(header_token: str = Security(api_key_header)) -> dict:
    clean_header_token = header_token.strip()
    matched_customer = None
    
    for secure_token, client_meta in CUSTOMER_REGISTRY.items():
        if secrets.compare_digest(clean_header_token, secure_token.strip()):
            matched_customer = client_meta
            break
            
    if not matched_customer:
        raise HTTPException(status_code=403, detail="Invalid gateway credentials")
        
    _enforce_rate_limit(clean_header_token, matched_customer["tier"])
    return matched_customer

# ----------------------------------------------------
# PYDANTIC DATA VALIDATORS & SCHEMAS
# ----------------------------------------------------
class LogSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def sanitize_search_query(cls, value: str) -> str:
        return sanitize_user_prompt(value)

class TranslationRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    target_language: str = Field(..., min_length=2, max_length=32)

    @field_validator("text")
    @classmethod
    def sanitize_translation_text(cls, value: str) -> str:
        return sanitize_user_prompt(value)

    @field_validator("target_language")
    @classmethod
    def language_must_be_allowed(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_LANGUAGES:
            raise ValueError("Unsupported target_language.")
        return normalized

class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)

    @field_validator("prompt")
    @classmethod
    def sanitize_chat_prompt(cls, value: str) -> str:
        return sanitize_user_prompt(value)

class VisaConsultationRequest(BaseModel):
    destination_country: str = Field(..., min_length=2, max_length=64)
    current_citizenship: str = Field(..., min_length=2, max_length=64)
    monthly_income_usd: float = Field(..., ge=0.0)
    query: str = Field(..., min_length=5, max_length=2000)

    @field_validator("query", "destination_country", "current_citizenship")
    @classmethod
    def guard_legal_inputs(cls, value: str) -> str:
        return sanitize_user_prompt(value)

class CustomerRegistrationRequest(BaseModel):
    email: str = Field(..., max_length=128)
    client_name: str = Field(..., min_length=2, max_length=64)

# ----------------------------------------------------
# THREAD-SAFE CLIENT LAYER LIFESPAN POOLS
# ----------------------------------------------------
openai_pool: AsyncOpenAI = None
anthropic_pool: AsyncAnthropic = None
pinecone_pool: Pinecone = None

# LOCAL DISK METADATA STORAGE SYSTEM
_REGISTRY_STORAGE_PATH = Path(__file__).resolve().parent / "registry.json"
_registry_file_lock = ThreadingLock()

def load_persisted_registry():
    with _registry_file_lock:
        if _REGISTRY_STORAGE_PATH.exists():
            try:
                with open(_REGISTRY_STORAGE_PATH, "r", encoding="utf-8") as f:
                    saved_data = json.load(f)
                    for token, metadata in saved_data.items():
                        CUSTOMER_REGISTRY[token] = metadata
                logger.info(f"Registry rehydrated dynamically. Loaded {len(saved_data)} profiles.")
            except Exception as err:
                logger.error(f"Failed to load local state database: {str(err)}")

def save_registry_to_disk():
    with _registry_file_lock:
        try:
            with open(_REGISTRY_STORAGE_PATH, "w", encoding="utf-8") as f:
                json.dump(CUSTOMER_REGISTRY, f, indent=4)
        except Exception as err:
            logger.error(f"Storage layer transaction error: {str(err)}")

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

def verify_engine_pool(pool_object, engine_name: str) -> None:
    if pool_object is None:
        logger.critical(f"State validation failure. Offline subsystem: {engine_name}")
        raise HTTPException(
            status_code=503, 
            detail=f"Gateway system routing error: [{engine_name}] layer is currently unavailable."
        )

# ----------------------------------------------------
# SYSTEM APP SETUP & FIREWALL MIDDLEWARE (HARDENED)
# ----------------------------------------------------
# VULNERABILITY #11 OPTIMIZATION ACTIVE: Hard-locked to APP_ENV definition context
app = FastAPI(
    title="Expat AI Advanced Enterprise Gateway",
    description="Multi-tenant gateway tracking client authorization strings.",
    version="4.4.0",
    lifespan=app_lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json"
)

_explicit_allowed_origins = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://vercel.app"
}
ALLOWED_ORIGIN_REGEX = re.compile(r"^https:\/\/.*\.onrender\.com$|^https:\/\/.*\.vercel\.app$")

@app.middleware("http")
async def enforce_production_ssl_and_cors(request: Request, call_next):
    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    _internal_whitelisted_paths = {"/", "/health", "/health/deep", "/docs", "/openapi.json", "/api/v1/webhooks/stripe"}
    
    if (IS_ON_RENDER or IS_PRODUCTION) and forwarded_proto == "http" and request.url.path not in _internal_whitelisted_paths:
        secure_url = request.url.replace(scheme="https")
        return RedirectResponse(secure_url, status_code=301)
        
    origin = request.headers.get("origin")
    response = await call_next(request)
    
    if origin:
        if origin in _explicit_allowed_origins or ALLOWED_ORIGIN_REGEX.match(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "false"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Nomad-Gateway-Token"
            
    return response

# ----------------------------------------------------
# SECURITY HARDENED LOGGING & EMBEDDING ENGINES
# ----------------------------------------------------
def sanitize_for_csv(text: str) -> str:
    if not text:
        return ""
    clean_text = text.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    if clean_text.startswith(('=', '+', '-', '@')):
        return f"'{clean_text}"
    return clean_text

def _sync_csv_append_worker(timestamp_str, customer_id, engine_name, task_type, clean_input, clean_output, total_cost):
    with _history_file_lock:
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

def _sync_pinecone_upsert(index_name: str, vectors: list, namespace: str):
    index_target = pinecone_pool.Index(index_name)
    index_target.upsert(vectors=vectors, namespace=namespace)

async def emit_stripe_metered_usage(customer_id: str, reseller_parent: str, calculated_cost: float, total_tokens: int):
    if customer_id.startswith("sandbox_") or reseller_parent != "direct":
        logger.info(f"Billing Bypass Log: Sandbox context tracking -> {customer_id} used {total_tokens} tokens.")
        return
    try:
        await asyncio.to_thread(
            stripe.billing.MeterEvent.create,
            event_name="ai_gateway_tokens",
            payload={"value": str(total_tokens), "stripe_customer_id": customer_id},
            timestamp=int(time.time())
        )
        logger.info(f"Stripe Usage Transmitted: Processed entry validation metrics for client {customer_id}")
    except Exception as e:
        logger.error(f"Stripe Metering Failure payload dropped: {str(e)}")

async def append_to_history_log(customer_id: str, reseller_parent: str, engine_name: str, task_type: str, user_input: str, ai_output: str, prompt_tokens: int = 0, completion_tokens: int = 0, pricing_key: str = None) -> None:
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_input = sanitize_for_csv(user_input)[:1000]
    clean_output = sanitize_for_csv(ai_output)[:2000]
    
    total_cost = 0.0
    if pricing_key and pricing_key in MODEL_PRICING:
        rates = MODEL_PRICING[pricing_key]
        input_cost = (prompt_tokens / 1000000.0) * rates["input"]
        output_cost = (completion_tokens / 1000000.0) * rates["output"]
        total_cost = round(input_cost + output_cost, 6)

    await emit_stripe_metered_usage(customer_id, reseller_parent, total_cost, (prompt_tokens + completion_tokens))

    try:
        await asyncio.to_thread(_sync_csv_append_worker, timestamp_str, customer_id, engine_name, task_type, clean_input, clean_output, total_cost)
    except Exception as log_err:
        logger.error(f"CSV Logging Fault trace: {str(log_err)}")

    if ENABLE_PINECONE_LOGGING and PINECONE_API_KEY:
        try:
            if openai_pool and pinecone_pool:
                text_to_embed = f"Client: {customer_id} | Input: {clean_input} | Output: {clean_output}"
                embedding_response = await openai_pool.embeddings.create(input=[text_to_embed], model="text-embedding-3-large", dimensions=2048)
                vector_values = embedding_response.data[0].embedding
                log_id = f"log_{secrets.token_hex(8)}"
                
                metadata_payload = {
                    "timestamp": timestamp_str, "customer_id": customer_id, "engine": engine_name, "mode": task_type,
                    "input_text": clean_input, "output_text": clean_output, "prompt_tokens": str(prompt_tokens),
                    "completion_tokens": str(completion_tokens), "total_tokens": str(prompt_tokens + completion_tokens), "estimated_cost_usd": str(total_cost)
                }
                current_namespace = datetime.now().strftime("logs-%Y-%m")
                await asyncio.to_thread(_sync_pinecone_upsert, PINECONE_INDEX_NAME, [{"id": log_id, "values": vector_values, "metadata": metadata_payload}], current_namespace)
            else:
                logger.error("Background task worker initialization exception context dropped.")
        except Exception as pinecone_err:
            logger.error(f"Pinecone Sync Disruption context log: {str(pinecone_err)}")

# ----------------------------------------------------
# SYSTEM VERSIONED ROUTING LAYER & IDEMPOTENCY SETS
# ----------------------------------------------------
v1_router = APIRouter(prefix="/api/v1")
_processed_stripe_events = deque(maxlen=5000)
_idempotency_lock = ThreadingLock()

@app.get("/health", tags=["Monitoring"])
async def system_health_check():
    return {"status": "healthy"}

@app.get("/health/deep", tags=["Monitoring"])
async def deep_health_check():
    checks = {}
    try:
        if openai_pool:
            await openai_pool.models.list(timeout=5.0)
            checks["openai"] = "ok"
        else:
            checks["openai"] = "offline"
    except Exception:
        checks["openai"] = "unreachable"

    try:
        if anthropic_pool:
            await anthropic_pool.models.list(timeout=5.0)
            checks["anthropic"] = "ok"
        else:
            checks["anthropic"] = "offline"
    except Exception:
        checks["anthropic"] = "unreachable"

    try:
        if pinecone_pool:
            import asyncio
            await asyncio.to_thread(pinecone_pool.describe_index, PINECONE_INDEX_NAME)
            checks["pinecone"] = "ok"
        else:
            checks["pinecone"] = "offline"
    except Exception:
        checks["pinecone"] = "unreachable"

    is_degraded = any(status in {"unreachable", "offline"} for status in checks.values())
    return {"status": "degraded" if is_degraded else "healthy", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "checks": checks}

@app.post("/api/v1/webhooks/stripe", tags=["Automated Billing Engine"])
async def stripe_billing_webhook(request: Request, x_stripe_signature: str = Header(None)):
    if not x_stripe_signature:
        logger.error("Unsigned transaction payload intercepted at billing route.")
        raise HTTPException(status_code=400, detail="Missing verification headers.")
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Billing webhook configuration offline.")
        
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, x_stripe_signature, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        logger.error(f"Stripe signature verification failed: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid billing signature payload.")

    event_id = event.get("id")
    with _idempotency_lock:
        if event_id in _processed_stripe_events:
            logger.info(f"Duplicate Webhook Intercepted: Event [{event_id}] already executed.")
            return {"status": "duplicate_ignored", "processed": True}
        _processed_stripe_events.append(event_id)

    if event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        stripe_customer_id = subscription["customer"]
        for token, meta in CUSTOMER_REGISTRY.items():
            if meta["customer_id"] == stripe_customer_id:
                CUSTOMER_REGISTRY[token]["tier"] = "free"
                CUSTOMER_REGISTRY[token]["monthly_spending_cap"] = 5.00
                logger.warning(f"Subscription Terminated: Customer {stripe_customer_id} downgraded to free.")
                break
        save_registry_to_disk()

    elif event["type"] in {"customer.subscription.created", "customer.subscription.updated"}:
        subscription = event["data"]["object"]
        stripe_customer_id = subscription["customer"]
        stripe_price_id = subscription["items"]["data"]["price"]["id"]
        status = subscription["status"]
        
        new_tier = "free"
        spending_cap = 5.00
        if stripe_price_id == STRIPE_PRICE_ID_PRO:
            new_tier = "pro"
            spending_cap = 50.00
        elif stripe_price_id == STRIPE_PRICE_ID_ENTERPRISE:
            new_tier = "enterprise"
            spending_cap = 500.00
            
        has_updated = False
        for token, meta in CUSTOMER_REGISTRY.items():
            if meta["customer_id"] == stripe_customer_id:
                if status == "active":
                    CUSTOMER_REGISTRY[token]["tier"] = new_tier
                    CUSTOMER_REGISTRY[token]["monthly_spending_cap"] = spending_cap
                    logger.info(f"Subscription Verified: Customer {stripe_customer_id} moved to [{new_tier.upper()}].")
                else:
                    CUSTOMER_REGISTRY[token]["tier"] = "free"
                    CUSTOMER_REGISTRY[token]["monthly_spending_cap"] = 5.00
                has_updated = True
                break
        if has_updated:
            save_registry_to_disk()

    return {"status": "success", "processed": True}

@app.post("/api/v1/checkout/session", tags=["Automated Billing Engine"])
async def create_nomad_checkout_session(payload: CustomerRegistrationRequest):
    try:
        customer = await asyncio.to_thread(stripe.Customer.create, email=payload.email, name=payload.client_name)
        generated_token = f"nvt_{secrets.token_urlsafe(32)}"
        CUSTOMER_REGISTRY[generated_token] = {
            "customer_id": customer["id"], "tier": "free", "monthly_spending_cap": 5.00, "current_month_spend": 0.0, "reseller_parent": "direct"
        }
        save_registry_to_disk()
        
        session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            customer=customer["id"], payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_ID_PRO, "quantity": 1}], mode="subscription",
            success_url="https://your-app-portal.com", cancel_url="https://your-app-portal.com",
        )
        return {"registration_status": "pending_payment", "assigned_gateway_token": generated_token, "stripe_checkout_redirect_url": session["url"]}
    except Exception as err:
        logger.error(f"Checkout Session Generation Interruption: {str(err)}")
        raise HTTPException(status_code=500, detail="Failed to initialize user checkout sequence.")

@v1_router.post("/translate", tags=["Proxy Engines"])
async def optimized_translation(payload: TranslationRequest, background_tasks: BackgroundTasks, client_auth: dict = Depends(validate_gateway_token)):
    verify_engine_pool(openai_pool, "OpenAI")
    current_spend = client_auth.get("current_month_spend", 0.0)
    max_cap = client_auth.get("monthly_spending_cap", 5.00)
    if current_spend >= max_cap:
        raise HTTPException(status_code=402, detail="Payment Required: Monthly platform budget threshold exceeded.")

    assigned_model = "gpt-4o"
    pricing_key = "openai-gpt-4o"
    if client_auth["tier"] == "free":
        assigned_model = "gpt-4o-mini"
        pricing_key = "openai-gpt-4o-mini"
        
    target = payload.target_language.strip().lower()
    premium_languages = frozenset({"arabic", "bengali", "czech", "danish", "dutch", "finnish", "greek", "hebrew", "hindi", "hungarian", "indonesian", "italian", "korean", "malay", "norwegian", "polish", "portuguese", "romanian", "russian", "spanish", "swedish", "thai", "turkish", "ukrainian", "urdu", "vietnamese"})
    if client_auth["tier"] == "free" and target in premium_languages:
        raise HTTPException(status_code=402, detail="Premium Subsystem Language pairing requirements require Pro or Enterprise plans.")

    try:
        async with asyncio.timeout(25.0):
            response = await openai_pool.chat.completions.create(
                model=assigned_model, messages=[{"role": "system", "content": f"Translate the user text into fluent {payload.target_language}."}, {"role": "user", "content": payload.text}], temperature=0.2
            )
        content = response.choices.message.content or ""
        transformed_output = content.strip()
        usage = response.usage
        p_tok, c_tok = (usage.prompt_tokens, usage.completion_tokens) if usage else (0, 0)
        
        if pricing_key in MODEL_PRICING:
            rates = MODEL_PRICING[pricing_key]
            cost = ((p_tok / 1000000.0) * rates["input"]) + ((c_tok / 1000000.0) * rates["output"])
            for token, meta in CUSTOMER_REGISTRY.items():
                if meta["customer_id"] == client_auth["customer_id"]:
                    CUSTOMER_REGISTRY[token]["current_month_spend"] = round(current_spend + cost, 6)
                    break
        background_tasks.add_task(append_to_history_log, client_auth["customer_id"], client_auth["reseller_parent"], f"OpenAI ({assigned_model})", f"Translation ({payload.target_language})", payload.text, transformed_output, p_tok, c_tok, pricing_key)
        return {"resolved_by": f"OpenAI ({assigned_model})", "transformed_text": transformed_output}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Upstream completion transaction timed out at the route boundary.")
    except Exception as err:
        logger.error(f"Translation Processing Crash Traceback: {str(err)}")
        raise HTTPException(status_code=500, detail="Translation service processing failed.")

@v1_router.post("/claude/chat", tags=["Proxy Engines"])
async def optimized_claude_chat(payload: ChatRequest, background_tasks: BackgroundTasks, client_auth: dict = Depends(validate_gateway_token)):
    verify_engine_pool(anthropic_pool, "Anthropic")
    current_spend = client_auth.get("current_month_spend", 0.0)
    max_cap = client_auth.get("monthly_spending_cap", 5.00)
    if current_spend >= max_cap:
        raise HTTPException(status_code=402, detail="Payment Required: Monthly platform budget threshold exceeded.")
    if "anthropic-sonnet" not in TIER_PROFILES[client_auth["tier"]]["allowed_models"]:
        raise HTTPException(status_code=403, detail=f"Access Forbidden: Model access restricted on plan tier [{client_auth['tier'].upper()}].")

    try:
        async with asyncio.timeout(25.0):
            response = await anthropic_pool.messages.create(
                model=ANTHROPIC_MODEL_NAME, max_tokens=1024, messages=[{"role": "user", "content": payload.prompt}], system="You are an advanced software architect AI. Provide concise answers."
            )
        resolved_response = response.content[0].text.strip()
        usage = response.usage
        p_tok, c_tok = (usage.input_tokens, usage.output_tokens) if usage else (0, 0)
        
        rates = MODEL_PRICING["anthropic-sonnet"]
        cost = ((p_tok / 1000000.0) * rates["input"]) + ((c_tok / 1000000.0) * rates["output"])
        for token, meta in CUSTOMER_REGISTRY.items():
            if meta["customer_id"] == client_auth["customer_id"]:
                CUSTOMER_REGISTRY[token]["current_month_spend"] = round(current_spend + cost, 6)
                break

        background_tasks.add_task(
            append_to_history_log, 
            client_auth["customer_id"], client_auth["reseller_parent"],
            f"Anthropic ({ANTHROPIC_MODEL_NAME})", "Architect Chat Prompt", 
            payload.prompt, resolved_response, p_tok, c_tok, "anthropic-sonnet"
        )
        return {"resolved_by": f"Anthropic ({ANTHROPIC_MODEL_NAME})", "response_payload": resolved_response}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Upstream completion transaction timed out at the route boundary.")
    except Exception:
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail="Chat service unavailable")

@v1_router.post("/visa/advise", tags=["Expat Legal Core"])
async def generate_visa_legal_advice(payload: VisaConsultationRequest, background_tasks: BackgroundTasks, client_auth: dict = Depends(validate_gateway_token)):
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
        async with asyncio.timeout(25.0):
            embedding_response = await openai_pool.embeddings.create(input=[search_prompt], model="text-embedding-3-large", dimensions=2048)
            query_vector = embedding_response.data.embedding

            index_target = pinecone_pool.Index(PINECONE_INDEX_NAME)
            raw_laws = await asyncio.to_thread(index_target.query, vector=query_vector, top_k=3, include_metadata=True, namespace="global-immigration-statutes")
            context_snippets = []
            for match in raw_laws.get("matches", []):
                if match.get("score", 0) >= 0.15:
                    meta = match.get("metadata", {})
                    context_snippets.append(f"Source [{meta.get('document_id', 'Immigration law')}]: {meta.get('text_extract', '')}")
            laws_context = "\n\n".join(context_snippets) if context_snippets else "No specific statutory text matches found."

            system_instruction = ("You are an elite international immigration attorney specializing in digital nomad visas.\nAnalyze the verified regulatory context files provided below and give precise, structured advice.\nAlways include a mandatory section at the very top titled 'REGULATORY LEGAL DISCLAIMER' explaining this does not constitute formal legal representation.")
            user_content = f"CUSTOMER PROFILE:\nPassport: {payload.current_citizenship}\nTarget: {payload.destination_country}\nIncome: ${payload.monthly_income_usd:.2f}/mo\n\nREFERENCE DATA:\n{laws_context}\n\nQUERY:\n{payload.query}"

            response = await anthropic_pool.messages.create(
                model=ANTHROPIC_MODEL_NAME, max_tokens=2048, temperature=0.1, system=system_instruction, messages=[{"role": "user", "content": user_content}]
            )
        resolved_advice = response.content.text.strip()
        usage = response.usage
        p_tok, c_tok = (usage.input_tokens, usage.output_tokens) if usage else (0, 0)
        
        rates = MODEL_PRICING["anthropic-sonnet"]
        cost = ((p_tok / 1000000.0) * rates["input"]) + ((c_tok / 1000000.0) * rates["output"])
        for token, meta in CUSTOMER_REGISTRY.items():
            if meta["customer_id"] == client_auth["customer_id"]:
                CUSTOMER_REGISTRY[token]["current_month_spend"] = round(current_spend + cost, 6)
                break
        background_tasks.add_task(append_to_history_log, client_auth["customer_id"], client_auth["reseller_parent"], f"Anthropic ({ANTHROPIC_MODEL_NAME})", f"Visa Advisor ({payload.destination_country})", payload.query, resolved_advice, p_tok, c_tok, "anthropic-sonnet")
        return {"resolved_by": "Expat Legal Advisory Core (Claude 3.5 Sonnet)", "account_tier": client_auth["tier"], "legal_context_matches_found": len(context_snippets), "advice_payload": resolved_advice}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Upstream processing timed out at the route boundary.")
    except Exception as err:
        logger.error(f"Visa Advisor Routing Engine Malfunction: {str(err)}")
        raise HTTPException(status_code=500, detail="Immigration legal advisory engine is temporarily offline.")

@v1_router.post("/logs/search", tags=["Enterprise Log Retrieval"])
async def secure_vector_log_search(payload: LogSearchRequest, client_auth: dict = Depends(validate_gateway_token)):
    verify_engine_pool(openai_pool, "OpenAI")
    verify_engine_pool(pinecone_pool, "Pinecone")
    try:
        async with asyncio.timeout(25.0):
            embedding_response = await openai_pool.embeddings.create(input=[payload.query], model="text-embedding-3-large", dimensions=2048)
            query_vector = embedding_response.data.embedding
            
            current_date = datetime.now()
            current_namespace = current_date.strftime("logs-%Y-%m")
            if current_date.month == 1:
                prev_namespace = f"logs-{current_date.year - 1}-12"
            else:
                prev_namespace = f"logs-{current_date.year}-{str(current_date.month - 1).zfill(2)}"
                
            namespaces_to_scan = [current_namespace, prev_namespace]
            index_target = pinecone_pool.Index(PINECONE_INDEX_NAME)
            
            all_matches = []
            for ns in namespaces_to_scan:
                try:
                    search_results = await asyncio.to_thread(index_target.query, vector=query_vector, top_k=payload.top_k, include_metadata=True, namespace=ns, filter={"customer_id": {"$eq": client_auth["customer_id"]}})
                    all_matches.extend(search_results.get("matches", []))
                except Exception as ns_err:
                    logger.warning(f"Skipped partition namespace scanning boundary [{ns}]: {str(ns_err)}")

        all_matches = sorted(all_matches, key=lambda x: x.get("score", 0), reverse=True)[:payload.top_k]
        CONFIDENCE_THRESHOLD = 0.10
        parsed_logs = []
        for match in all_matches:
            score = round(match.get("score", 0), 4)
            if score >= CONFIDENCE_THRESHOLD:
                metadata = match.get("metadata", {})
                clean_payload = {k: (str(v) if not isinstance(v, list) else [str(x) for x in v]) for k, v in metadata.items()}
                parsed_logs.append({"log_id": match.get("id"), "similarity_score": score, "data_payload": clean_payload})
        return {"search_query": payload.query, "partitions_scanned": namespaces_to_scan, "records_found_count": len(parsed_logs), "results": parsed_logs}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Log retrieval search timed out.")
    except Exception as err:
        logger.error(f"Search Fault Error: {str(err)}")
        raise HTTPException(status_code=500, detail="Log retrieval service unavailable")

# ====================================================================
# 🟢 ON-DEMAND DYNAMIC DOCUMENTATION BYPASS (PLACE AT BOTTOM OF PART 7)
# ====================================================================
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

@v1_router.get("/gateway/docs", include_in_schema=False)
async def dynamic_developer_docs_bypass(token: str = None):
    """
    VULNERABILITY #11 HARDENING BYPASS: Automated Developer Token Verification.
    Dynamically authenticates and renders the interactive Swagger UI panel on-demand
    in production environments only if a verified administrative token is present.
    """
    if not token:
        raise HTTPException(status_code=403, detail="Access Denied: Missing authorization query token.")
        
    clean_token = token.strip()
    matched_meta = None
    
    # Securely verify if the provided query string matches a registered developer account
    for secure_token, meta in CUSTOMER_REGISTRY.items():
        if secrets.compare_digest(clean_token, secure_token.strip()):
            matched_meta = meta
            break
            
    if not matched_meta:
        raise HTTPException(status_code=403, detail="Access Denied: Invalid gateway credentials.")
        
    # Enforce that only Pro or Enterprise tier tokens can unlock the blueprint views
    if matched_meta["tier"] not in {"pro", "enterprise"}:
        raise HTTPException(status_code=403, detail="Access Denied: Insufficient authorization clearing tier.")

    # Render and return the complete interactive Swagger UI HTML package inline
    return get_swagger_ui_html(
        openapi_url="/api/v1/gateway/openapi.json?token=" + clean_token,
        title="Authorized Enterprise Gateway Documentation Panel"
    )

@v1_router.get("/gateway/openapi.json", include_in_schema=False)
async def dynamic_developer_openapi_schema(token: str = None):
    """
    Serves the supporting schema data strings securely to authorized tokens.
    """
    if not token:
        raise HTTPException(status_code=403, detail="Access Denied.")
        
    clean_token = token.strip()
    is_valid = any(secrets.compare_digest(clean_token, k.strip()) for k in CUSTOMER_REGISTRY.keys())
    if not is_valid:
        raise HTTPException(status_code=403, detail="Access Denied.")
        
    return get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes
    )

app.include_router(v1_router)
