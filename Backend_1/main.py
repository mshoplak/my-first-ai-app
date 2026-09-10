import logging
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
from threading import Lock

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security, BackgroundTasks, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse, RedirectResponse
from openai import AsyncOpenAI
from pinecone import Pinecone
from pydantic import BaseModel, Field, field_validator
import stripe

# ---------------------------------------------------- #
# 🌍 ENVIRONMENT SETUP & SECURITY INITIALIZATION       #
# ---------------------------------------------------- #
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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ai-app-logs")
ENABLE_PINECONE_LOGGING = os.getenv("ENABLE_PINECONE_LOGGING", "true").lower() in ("true", "1")
ANTHROPIC_MODEL_NAME = os.getenv("ANTHROPIC_MODEL_NAME", "claude-3-5-sonnet-20241022")

# STRIPE ADDITIONS: Webhook secrets and Product Price lookup mappings
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_ID_PRO = os.getenv("STRIPE_PRICE_ID_PRO")
STRIPE_PRICE_ID_ENTERPRISE = os.getenv("STRIPE_PRICE_ID_ENTERPRISE")

_HISTORY_LOG_PATH = Path(__file__).resolve().parent / "history.csv"
_history_file_lock = Lock()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("expat-gateway")

# ---------------------------------------------------- #
# 🏆 MONETIZATION TIER CONFIGURATION ARRAYS             #
# ---------------------------------------------------- #
TIER_PROFILES = {
    "free": {"rate_limit": 5, "window": 60, "allowed_models": {"openai-gpt-4o"}},
    "pro": {"rate_limit": 60, "window": 60, "allowed_models": {"openai-gpt-4o", "anthropic-sonnet"}},
    "enterprise": {"rate_limit": 300, "window": 60, "allowed_models": {"openai-gpt-4o", "anthropic-sonnet"}}
}

CUSTOMER_REGISTRY: dict[str, dict] = {}
raw_keys_string = os.getenv("CUSTOMER_GATEWAY_KEYS", "").strip().strip('"').strip("'")
if raw_keys_string:
    for pair in raw_keys_string.split(","):
        clean_pair = pair.strip()
        parts = clean_pair.split(":")
        if len(parts) >= 2:
            token = parts[0].strip()
            client_name = parts[1].strip()
            # Default to free tier on boot; Stripe hook will upgrade dynamically
            tier = parts[2].strip().lower() if len(parts) >= 3 and parts[2].strip().lower() in TIER_PROFILES else "free"
            reseller_parent = parts[3].strip() if len(parts) == 4 else "direct"
            
            CUSTOMER_REGISTRY[token] = {
                "customer_id": client_name,
                "tier": tier,
                "reseller_parent": reseller_parent
            }

# Backwards compatibility map for original dictionary checks
CUSTOMER_KEYS = {k: v["customer_id"] for k, v in CUSTOMER_REGISTRY.items()}

_missing = [name for name, value in (("OPENAI_API_KEY", OPENAI_API_KEY), ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY), ("PINECONE_API_KEY", PINECONE_API_KEY)) if not value]
if _missing or not CUSTOMER_REGISTRY:
    logger.error(f"❌ CONFIGURATION ERROR: Missing properties -> {_missing}")
    raise RuntimeError("CRITICAL ENVIRONMENT ERROR: Server initialization blocked.")
API_KEY_NAME = "X-Nomad-Gateway-Token"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

MODEL_PRICING = {
    "openai-gpt-4o": {"input": 2.50, "output": 10.00},
    "anthropic-sonnet": {"input": 3.00, "output": 15.00}
}

RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "30"))
RATE_LIMIT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = Lock()

# INPUT SANITIZATION AND PROMPT INJECTION GUARD
INJECTION_PATTERN = re.compile(
    r"(ignore\s+all\s+previous|system\s+prompt|developer\s+mode|override\s+instructions|you\s+are\s+now\s+a)",
    re.IGNORECASE
)

def sanitize_user_prompt(text: str) -> str:
    if INJECTION_PATTERN.search(text):
        logger.warning(f"🛡️ Prompt Injection Intercepted: Suspicious command strings removed.")
        raise HTTPException(status_code=400, detail="Security Flag: Request payload contains forbidden system override strings.")
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
        # Global eviction of stale tracking keys across ALL clients
        dead_keys = [k for k, v in _rate_buckets.items() if not v or (now - v[-1]) > window]
        for dk in dead_keys:
            del _rate_buckets[dk]
            
        bucket = _rate_buckets[token]
        while bucket and (now - bucket[0]) > window:
            bucket.popleft()
            
        if len(bucket) >= limit:
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded for tier [{tier.upper()}]. Try again later.")
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

# ---------------------------------------------------- #
# 📝 PYDANTIC DATA VALIDATORS & SCHEMAS               #
# ---------------------------------------------------- #
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
# ---------------------------------------------------- #
# 🔌 THREAD-SAFE CLIENT LAYER LIFESPAN POOLS           #
# ---------------------------------------------------- #
openai_pool: AsyncOpenAI = None
anthropic_pool: AsyncAnthropic = None
pinecone_pool: Pinecone = None

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    global openai_pool, anthropic_pool, pinecone_pool
    logger.info("Initializing explicit timeout AI and Database client sockets")
    openai_pool = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=30.0)
    anthropic_pool = AsyncAnthropic(api_key=ANTHROPIC_API_KEY, timeout=30.0)
    if PINECONE_API_KEY:
        pinecone_pool = Pinecone(api_key=PINECONE_API_KEY)
    yield
    logger.info("Closing active resource lanes safely")
    await openai_pool.close()
    await anthropic_pool.close()

# Type-safe operational gate ensuring safe state checking
def verify_engine_pool(pool_object, engine_name: str) -> None:
    if pool_object is None:
        logger.critical(f"State validation failure. Attempted call to offline subsystem: {engine_name}")
        raise HTTPException(
            status_code=503, 
            detail=f"Gateway system routing error: [{engine_name}] layer is currently unavailable."
        )

# ---------------------------------------------------- #
# 🛡️ SYSTEM APP AND ROUTING MIDDLEWARE FIREWALLS       #
# ---------------------------------------------------- #
_enable_docs = os.getenv("ENABLE_DOCS", "false" if IS_PRODUCTION else "true").lower() in {"1", "true", "yes"}
app = FastAPI(
    title="Expat AI Advanced Enterprise Gateway",
    description="Multi-tenant provider AI gateway tracking individual client authorization strings.",
    version="4.0.0",
    lifespan=app_lifespan,
    docs_url="/docs" if _enable_docs else None,
    redoc_url="/redoc" if _enable_docs else None,
    openapi_url="/openapi.json" if _enable_docs else None
)

_allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://onrender.com",
    "https://vercel.app"
]
ALLOWED_ORIGIN_REGEX = re.compile(r"^https:\/\/.*\.onrender\.com$|^https:\/\/.*\.vercel\.app$")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", API_KEY_NAME],
)

@app.middleware("http")
async def enforce_production_ssl_proxy(request: Request, call_next):
    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    _internal_whitelisted_paths = {"/", "/health", "/health/deep", "/docs", "/openapi.json", "/api/v1/webhooks/stripe"}
    
    # Global HTTP -> HTTPS 301 Redirect enforcement for production or platform lanes
    if (IS_ON_RENDER or IS_PRODUCTION) and forwarded_proto == "http" and request.url.path not in _internal_whitelisted_paths:
        secure_url = request.url.replace(scheme="https")
        return RedirectResponse(secure_url, status_code=301)
        
    return await call_next(request)
# ---------------------------------------------------- #
# 💾 SECURITY HARDENED VECTOR LOGGING ENGINE           #
# ---------------------------------------------------- #
def sanitize_for_csv(text: str) -> str:
    if not text:
        return ""
    # Wipe out tabs, newlines, and carriage returns to block malicious spreadsheet macro execution
    clean_text = text.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    if clean_text.startswith(('=', '+', '-', '@')):
        return f"'{clean_text}"
    return clean_text

def _sync_pinecone_upsert(index_name: str, vectors: list, namespace: str):
    """
    Isolated synchronous function executed inside an external worker thread
    to completely prevent blocking FastAPI's async event loop.
    """
    index_target = pinecone_pool.Index(index_name)
    index_target.upsert(vectors=vectors, namespace=namespace)

async def emit_stripe_metered_usage(customer_id: str, reseller_parent: str, calculated_cost: float, total_tokens: int):
    """
    Asynchronous hook dispatching exact cost usage metrics for usage-based monetization tracking.
    """
    logger.info(f"📊 [Stripe Billing Meter] Client: {customer_id} | Parent: {reseller_parent} | Billable Cost: ${calculated_cost:.6f} | Vol: {total_tokens} tokens")

async def append_to_history_log(
    customer_id: str,
    reseller_parent: str,
    engine_name: str,
    task_type: str,
    user_input: str,
    ai_output: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    pricing_key: str = None
) -> None:
    """
    Harden-Audit Process: Thread-isolated logger executing with thread-safe file locks, 
    automatic rolling size-cap rotations, and integrated metered billing hooks.
    """
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_input = sanitize_for_csv(user_input)[:1000]
    clean_output = sanitize_for_csv(ai_output)[:2000]
    
    input_cost = 0.0
    output_cost = 0.0
    total_cost = 0.0
    
    if pricing_key and pricing_key in MODEL_PRICING:
        rates = MODEL_PRICING[pricing_key]
        input_cost = (prompt_tokens / 1000000.0) * rates["input"]
        output_cost = (completion_tokens / 1000000.0) * rates["output"]
        total_cost = round(input_cost + output_cost, 6)

    # Dispatches usage tracking statistics instantly to meter records
    await emit_stripe_metered_usage(customer_id, reseller_parent, total_cost, (prompt_tokens + completion_tokens))

    # Wrapped inside the lock scope to eliminate file write race conditions entirely
    if os.getenv("ENABLE_HISTORY_LOGGING", "false").lower() in ("true", "1"):
        try:
            with _history_file_lock:
                MAX_SIZE_BYTES = 10 * 1024 * 1024 # 10MB Safety Cap Threshold
                if _HISTORY_LOG_PATH.exists() and _HISTORY_LOG_PATH.stat().st_size > MAX_SIZE_BYTES:
                    backup_path = _HISTORY_LOG_PATH.with_name("history_old.csv")
                    logger.info(f"🔄 Rotating history file: moving heavy log to {backup_path.name}")
                    if backup_path.exists():
                        backup_path.unlink()
                    _HISTORY_LOG_PATH.rename(backup_path)
                
                file_exists = _HISTORY_LOG_PATH.exists()
                with open(_HISTORY_LOG_PATH, mode="a", newline="", encoding="utf-8") as csv_file:
                    writer = csv.writer(csv_file)
                    if not file_exists:
                        writer.writerow(["Timestamp", "Authorized Client ID", "Engine", "Mode", "Input Payload", "AI Output Response", "Total Cost ($)"])
                    writer.writerow([timestamp_str, customer_id, engine_name, task_type, clean_input, clean_output, f"${total_cost:.6f}"])
        except Exception as log_err:
            logger.error(f"⚠️ CSV Log Fault: {str(log_err)}")

    # Hardened Background Thread Vector Injection Loop (2048 Dimensions)
    if ENABLE_PINECONE_LOGGING and PINECONE_API_KEY:
        try:
            if openai_pool and pinecone_pool:
                text_to_embed = f"Client: {customer_id} | Input: {clean_input} | Output: {clean_output}"
                embedding_response = await openai_pool.embeddings.create(
                    input=[text_to_embed],
                    model="text-embedding-3-large",
                    dimensions=2048
                )
                vector_values = embedding_response.data[0].embedding if hasattr(embedding_response.data[0], 'embedding') else embedding_response.data[0]['embedding']
                log_id = f"log_{secrets.token_hex(8)}"
                
                metadata_payload = {
                    "timestamp": timestamp_str,
                    "customer_id": customer_id,
                    "engine": engine_name,
                    "mode": task_type,
                    "input_text": clean_input,
                    "output_text": clean_output,
                    "prompt_tokens": str(prompt_tokens),
                    "completion_tokens": str(completion_tokens),
                    "total_tokens": str(prompt_tokens + completion_tokens),
                    "estimated_cost_usd": str(total_cost)
                }
                current_namespace = datetime.now().strftime("logs-%Y-%m")
                logger.info(f"🚀 [Background Task] Dispatching vector packet {log_id} to namespace: {current_namespace}")
                
                # Non-blocking thread offload execution
                await asyncio.to_thread(
                    _sync_pinecone_upsert,
                    PINECONE_INDEX_NAME,
                    [{"id": log_id, "values": vector_values, "metadata": metadata_payload}],
                    current_namespace
                )
            else:
                logger.error("⚠️ Background Task Aborted: Global connection pool elements are uninitialized.")
        except Exception as pinecone_err:
            logger.error(f"⚠️ Pinecone Background Task Sync Disruption: {str(pinecone_err)}")
# ---------------------------------------------------- #
# 🛰️ SYSTEM ROUTING ENDPOINTS & MONITORING             #
# ---------------------------------------------------- #
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
            checks["openai"] = "offline_pool"
    except Exception as err:
        logger.error(f"📡 Deep Probe Fault - OpenAI: {str(err)}")
        checks["openai"] = "unreachable"

    try:
        if anthropic_pool:
            await anthropic_pool.messages.create(
                model=ANTHROPIC_MODEL_NAME,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
                timeout=5.0
            )
            checks["anthropic"] = "ok"
        else:
            checks["anthropic"] = "offline_pool"
    except Exception as err:
        logger.error(f"📡 Deep Probe Fault - Anthropic: {str(err)}")
        checks["anthropic"] = "unreachable"

    try:
        if pinecone_pool:
            await asyncio.to_thread(pinecone_pool.describe_index, PINECONE_INDEX_NAME)
            checks["pinecone"] = "ok"
        else:
            checks["pinecone"] = "offline_pool"
    except Exception as err:
        logger.error(f"📡 Deep Probe Fault - Pinecone: {str(err)}")
        checks["pinecone"] = "unreachable"

    is_degraded = any(status in {"unreachable", "offline_pool"} for status in checks.values())
    return {
        "status": "degraded" if is_degraded else "healthy",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "checks": checks
    }

# ---------------------------------------------------- #
# 💳 STRIPE AUTOMATED LIVE BILLING WEBHOOK ROUTE        #
# ---------------------------------------------------- #
@app.post("/api/v1/webhooks/stripe", tags=["Automated Billing Engine"])
async def stripe_billing_webhook(request: Request, x_stripe_signature: str = Header(None)):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Billing webhook configuration offline.")
        
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, x_stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        logger.error(f"❌ Stripe signature verification failed: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid billing signature payload.")

    if event["type"] in {"customer.subscription.created", "customer.subscription.updated"}:
        subscription = event["data"]["object"]
        stripe_customer_id = subscription["customer"]
        stripe_price_id = subscription["items"]["data"][0]["price"]["id"]
        
        new_tier = "free"
        if stripe_price_id == STRIPE_PRICE_ID_PRO:
            new_tier = "pro"
        elif stripe_price_id == STRIPE_PRICE_ID_ENTERPRISE:
            new_tier = "enterprise"
            
        status = subscription["status"]
        
        for token, meta in CUSTOMER_REGISTRY.items():
            if meta["customer_id"] == stripe_customer_id:
                if status == "active":
                    CUSTOMER_REGISTRY[token]["tier"] = new_tier
                    logger.info(f"💳 Dynamic Upgrade: Client {stripe_customer_id} updated to tier [{new_tier.upper()}].")
                else:
                    CUSTOMER_REGISTRY[token]["tier"] = "free"
                    logger.warning(f"⚠️ Delinquent Subscription: Client {stripe_customer_id} reverted to free. Status: {status}")
                break

    return {"status": "success", "processed": True}

# ---------------------------------------------------- #
# 📡 CORE LLM RUNTIME TRANSACTION ROUTES                #
# ---------------------------------------------------- #
@app.post("/api/translate", tags=["OpenAI Core"])
async def optimized_translation(payload: TranslationRequest, background_tasks: BackgroundTasks, client_auth: dict = Depends(validate_gateway_token)):
    verify_engine_pool(openai_pool, "OpenAI")
    
    target = payload.target_language.strip().lower()
    premium_languages = frozenset({"arabic", "bengali", "czech", "danish", "dutch", "finnish", "greek", "hebrew", "hindi", "hungarian", "indonesian", "italian", "korean", "malay", "norwegian", "polish", "portuguese", "romanian", "russian", "swedish", "thai", "turkish", "ukrainian", "urdu", "vietnamese"})
    
    if client_auth["tier"] == "free" and target in premium_languages:
        raise HTTPException(status_code=402, detail="Payment Required: Rare or specialized language pairings require a Pro or Enterprise plan configuration.")

    try:
        response = await openai_pool.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": f"Translate the user text into fluent {payload.target_language}."},
                {"role": "user", "content": payload.text},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        transformed_output = content.strip()
        usage = response.usage
        p_tok = usage.prompt_tokens if usage else 0
        c_tok = usage.completion_tokens if usage else 0
        
        background_tasks.add_task(
            append_to_history_log, 
            client_auth["customer_id"], client_auth["reseller_parent"],
            "OpenAI (gpt-4o)", f"Translation ({payload.target_language})", 
            payload.text, transformed_output, p_tok, c_tok, "openai-gpt-4o"
        )
        return {"resolved_by": "OpenAI (gpt-4o)", "transformed_text": transformed_output}
    except Exception as err:
        logger.error(f"❌ Translation Processing Crash Traceback: {str(err)}")
        raise HTTPException(status_code=500, detail="Translation service unavailable")

@app.post("/api/claude/chat", tags=["Anthropic Core"])
async def optimized_claude_chat(payload: ChatRequest, background_tasks: BackgroundTasks, client_auth: dict = Depends(validate_gateway_token)):
    verify_engine_pool(anthropic_pool, "Anthropic")
    
    if "anthropic-sonnet" not in TIER_PROFILES[client_auth["tier"]]["allowed_models"]:
        raise HTTPException(status_code=403, detail=f"Access Forbidden: Model access restricted on plan tier [{client_auth['tier'].upper()}]. Upgrade to Pro.")

    try:
        response = await anthropic_pool.messages.create(
            model=ANTHROPIC_MODEL_NAME,
            max_tokens=1024,
            messages=[{"role": "user", "content": payload.prompt}],
            system="You are an advanced software architect AI. Provide concise answers.",
        )
        resolved_response = response.content[0].text.strip()
        usage = response.usage
        p_tok = usage.input_tokens if usage else 0
        c_tok = usage.output_tokens if usage else 0
        
        background_tasks.add_task(
            append_to_history_log, 
            client_auth["customer_id"], client_auth["reseller_parent"],
            f"Anthropic ({ANTHROPIC_MODEL_NAME})", "Architect Chat Prompt", 
            payload.prompt, resolved_response, p_tok, c_tok, "anthropic-sonnet"
        )
        return {"resolved_by": f"Anthropic ({ANTHROPIC_MODEL_NAME})", "response_payload": resolved_response}
    except Exception:
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail="Chat service unavailable")

@app.post("/api/visa/advise", tags=["Expat Legal Core"])
async def generate_visa_legal_advice(payload: VisaConsultationRequest, background_tasks: BackgroundTasks, client_auth: dict = Depends(validate_gateway_token)):
    if client_auth["tier"] == "free":
        raise HTTPException(status_code=402, detail="Premium Subsystem: The Visa & Immigration Legal Advisory Engine requires an active Pro or Enterprise plan.")

    verify_engine_pool(openai_pool, "OpenAI")
    verify_engine_pool(anthropic_pool, "Anthropic")
    verify_engine_pool(pinecone_pool, "Pinecone")

    try:
        search_prompt = f"Visa options for {payload.current_citizenship} citizen moving to {payload.destination_country}. Income: ${payload.monthly_income_usd}/mo. Context: {payload.query}"
        embedding_response = await openai_pool.embeddings.create(
            input=[search_prompt],
            model="text-embedding-3-large",
            dimensions=2048
        )
        query_vector = embedding_response.data[0].embedding if hasattr(embedding_response.data[0], 'embedding') else embedding_response.data[0]['embedding']

        index_target = pinecone_pool.Index(PINECONE_INDEX_NAME)
        raw_laws = await asyncio.to_thread(
            index_target.query,
            vector=query_vector,
            top_k=3,
            include_metadata=True,
            namespace="global-immigration-statutes"
        )

        context_snippets = []
        for match in raw_laws.get("matches", []):
            if match.get("score", 0) >= 0.15:
                meta = match.get("metadata", {})
                context_snippets.append(f"Source [{meta.get('document_id', 'Immigration law')}]: {meta.get('text_extract', '')}")

        laws_context = "\n\n".join(context_snippets) if context_snippets else "No specific statutory text matches found in database."

        system_instruction = (
            "You are an elite international immigration attorney specializing in digital nomad visas, remote worker tax schemes, and residency pathways.\n"
            "Analyze the verified regulatory context files provided below and give precise, highly structured advice.\n"
            "Always include a mandatory, explicit section at the very top titled '⚖️ REGULATORY LEGAL DISCLAIMER' explaining that this is informational AI advice and does not constitute official legal representation."
        )
        
        user_content = (
            f"CUSTOMER PROFILE:\n"
            f"- Current Passport: {payload.current_citizenship}\n"
            f"- Intended Target Country: {payload.destination_country}\n"
            f"- Documented Remote Revenue: ${payload.monthly_income_usd:.2f} USD / month\n\n"
            f"VERIFIED REGULATORY REFERENCE MATERIAL:\n{laws_context}\n\n"
            f"USER QUERY:\n{payload.query}"
        )

        response = await anthropic_pool.messages.create(
            model=ANTHROPIC_MODEL_NAME,
            max_tokens=2048,
            temperature=0.1,
            system=system_instruction,
            messages=[{"role": "user", "content": user_content}]
        )
        
        resolved_advice = response.content[0].text.strip()
        usage = response.usage

        background_tasks.add_task(
            append_to_history_log,
            client_auth["customer_id"], client_auth["reseller_parent"],
            f"Anthropic ({ANTHROPIC_MODEL_NAME})", f"Visa Advisor ({payload.destination_country})",
            payload.query, resolved_advice, usage.input_tokens, usage.output_tokens, "anthropic-sonnet"
        )

        return {
            "resolved_by": "Expat Legal Advisory Core (Claude 3.5 Sonnet)",
            "account_tier": client_auth["tier"],
            "legal_context_matches_found": len(context_snippets),
            "advice_payload": resolved_advice
        }
    except Exception as err:
        logger.error(f"❌ Visa Advisor Routing Engine Malfunction: {str(err)}")
        raise HTTPException(status_code=500, detail="Immigration legal advisory engine is temporarily offline.")

@app.post("/api/logs/search", tags=["Enterprise Log Retrieval"])
async def secure_vector_log_search(payload: LogSearchRequest, customer_id: str = Depends(validate_gateway_token)):
    verify_engine_pool(openai_pool, "OpenAI")
    verify_engine_pool(pinecone_pool, "Pinecone")
    try:
        embedding_response = await openai_pool.embeddings.create(
            input=[payload.query],
            model="text-embedding-3-large",
            dimensions=2048
        )
        query_vector = embedding_response.data[0].embedding
        current_namespace = datetime.now().strftime("logs-%Y-%m")
        
        index_target = pinecone_pool.Index(PINECONE_INDEX_NAME)
        search_results = await asyncio.to_thread(
            index_target.query,
            vector=query_vector,
            top_k=payload.top_k,
            include_metadata=True,
            namespace=current_namespace,
            filter={"customer_id": {"$eq": customer_id["customer_id"]}}
        )
        
        CONFIDENCE_THRESHOLD = 0.10
        parsed_logs = []
        for match in search_results.get("matches", []):
            score = round(match.get("score", 0), 4)
            if score >= CONFIDENCE_THRESHOLD:
                metadata = match.get("metadata", {})
                clean_payload = {}
                for k, v in metadata.items():
                    if isinstance(v, list):
                        clean_payload[k] = [str(x) for x in v]
                    else:
                        clean_payload[k] = str(v)
                parsed_logs.append({
                    "log_id": match.get("id"),
                    "similarity_score": score,
                    "data_payload": clean_payload
                })
                
        return {
            "search_query": payload.query,
            "partition_scanned": current_namespace,
            "confidence_threshold_applied": CONFIDENCE_THRESHOLD,
            "records_found_count": len(parsed_logs),
            "results": parsed_logs
        }
    except Exception as err:
        logger.error(f"⚠️ Search Fault Error: {str(err)}")
        raise HTTPException(status_code=500, detail="Log retrieval service unavailable")
