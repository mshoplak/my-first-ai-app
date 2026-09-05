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
from fastapi import Depends, FastAPI, HTTPException, Security, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from pinecone import Pinecone
from pydantic import BaseModel, Field, field_validator

# ----------------------------------------------------
# 🌍 HIGH-RESILIENCE ENVIRONMENT SETUP
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
# 🔒 SECURE SYSTEM ENGINE INITIALIZATION
# ----------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ai-app-logs")
ENABLE_PINECONE_LOGGING = os.getenv("ENABLE_PINECONE_LOGGING", "true").lower() in ("true", "1")
ANTHROPIC_MODEL_NAME = os.getenv("ANTHROPIC_MODEL_NAME", "claude-3-5-sonnet-20241022")

_HISTORY_LOG_PATH = Path(__file__).resolve().parent / "history.csv"
_history_file_lock = Lock()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("expat-gateway")

# Multi-Tenant Key Mappings
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
        ("PINECONE_API_KEY", PINECONE_API_KEY),
    ) if not value
]

if _missing or not CUSTOMER_KEYS:
    logger.error(f"❌ CONFIGURATION ERROR: Missing system environment properties -> {_missing}")
    raise RuntimeError("CRITICAL ENVIRONMENT ERROR: Server initialization blocked. Check private system logs.")

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
    """
    High-Resilience Multi-Tenant Rate Limiter: Incorporates an active memory eviction
    sweep to prune stale client tracking queues from server RAM dynamically.
    """
    now = time.monotonic()
    with _rate_lock:
        # 1. EVICTION PASS: Scan and prune stale token queues to prevent RAM memory leaks
        stale_tokens = [
            k for k, v in _rate_buckets.items() 
            if v and (now - v[-1]) > RATE_LIMIT_WINDOW_SEC * 2
        ]
        for k in stale_tokens:
            del _rate_buckets[k]

        # 2. STANDARD RATE CHECK: Enforce active sliding window limitations
        bucket = _rate_buckets[token]
        # FIXED CRITICAL ARRAY INDEX: Added bracket 0 to grab the absolute float inside the deque
        while bucket and (now - bucket[0]) > RATE_LIMIT_WINDOW_SEC:
            bucket.popleft()
            
        if len(bucket) >= RATE_LIMIT_MAX:
            raise HTTPException(
                status_code=429, 
                detail="Rate limit exceeded. Try again later."
            )
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
# ----------------------------------------------------
# 📝 PYDANTIC INTERFACES & SCHEMAS
# ----------------------------------------------------
class LogSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(5, ge=1, le=20)

class TranslationRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    target_language: str = Field(..., min_length=2, max_length=32)

    @field_validator("target_language")
    @classmethod
    def language_must_be_allowed(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_LANGUAGES:
            raise ValueError("Unsupported target_language.")
        return normalized

class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)

# ----------------------------------------------------
# 🔌 LIFESPAN CONNECTION POOLS
# ----------------------------------------------------
gateway_state: dict = {}

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    logger.info("Initializing AI and Database client pools with explicit timeouts")
    gateway_state["openai"] = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=30.0)
    gateway_state["anthropic"] = AsyncAnthropic(api_key=ANTHROPIC_API_KEY, timeout=30.0)
    
    if PINECONE_API_KEY:
        gateway_state["pinecone"] = Pinecone(api_key=PINECONE_API_KEY)
    yield
    logger.info("Closing AI client connections")
    await gateway_state["openai"].close()
    await gateway_state["anthropic"].close()

# ----------------------------------------------------
# 🚀 NATIVE APP MOUNTING & FIREWALL MIDDLEWARE
# ----------------------------------------------------
_enable_docs = os.getenv("ENABLE_DOCS", "false" if IS_PRODUCTION else "true").lower() in {"1", "true", "yes"}

app = FastAPI(
    title="Expat AI Advanced Enterprise Gateway",
    description="Multi-tenant provider AI gateway tracking individual client authorization strings.",
    version="2.6.0",
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", API_KEY_NAME],
)

@app.middleware("http")
async def enforce_production_ssl_proxy(request: Request, call_next):
    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    
    if IS_ON_RENDER and forwarded_proto == "http" and request.url.path not in {"/health", "/health/deep"}:
        return JSONResponse(
            status_code=400,
            content={"detail": "Bad Request: Security protocol infraction. All transactions must run over HTTPS lanes."}
        )
    return await call_next(request)
# ----------------------------------------------------
# 💾 HIGH-RESILIENCE BACKGROUND LOGGING ENGINE
# ----------------------------------------------------
def sanitize_for_csv(text: str) -> str:
    if not text:
        return ""
    if text.startswith(('=', '+', '-', '@')):
        return f"'{text}"
    return text

async def append_to_history_log(customer_id: str, engine_name: str, task_type: str, user_input: str, ai_output: str) -> None:
    """
    Background Task Routine: Simultaneously writes local CSV audits while 
    streaming 2048 vector embeddings to partitioned Pinecone Cloud namespaces.
    """
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_input = sanitize_for_csv(user_input)[:1000]
    clean_output = sanitize_for_csv(ai_output)[:2000]

    if os.getenv("ENABLE_HISTORY_LOGGING", "false").lower() in ("true", "1"):
        try:
            if not _HISTORY_LOG_PATH.exists() or _HISTORY_LOG_PATH.stat().st_size <= 10 * 1024 * 1024:
                file_exists = _HISTORY_LOG_PATH.exists()
                with _history_file_lock:
                    with open(_HISTORY_LOG_PATH, mode="a", newline="", encoding="utf-8") as csv_file:
                        writer = csv.writer(csv_file)
                        if not file_exists:
                            writer.writerow(["Timestamp", "Authorized Client ID", "Engine", "Mode", "Input Payload", "AI Output Response"])
                        writer.writerow([timestamp_str, customer_id, engine_name, task_type, clean_input, clean_output])
        except Exception as log_err:
            logger.error(f"⚠️ CSV Log Fault: {str(log_err)}")

    if ENABLE_PINECONE_LOGGING and PINECONE_API_KEY:
        try:
            openai_client = gateway_state.get("openai")
            pc_client = gateway_state.get("pinecone")
            
            if openai_client and pc_client:
                text_to_embed = f"Client: {customer_id} | Input: {clean_input} | Output: {clean_output}"
                
                embedding_response = await openai_client.embeddings.create(
                    input=[text_to_embed],
                    model="text-embedding-3-large",
                    dimensions=2048
                )
                # FIXED EMBEDDING ARRAYS: Safely extracts coordinates from data index 0 to clear out internal list errors
                vector_values = embedding_response.data[0].embedding
                
                log_id = f"log_{secrets.token_hex(8)}"
                metadata_payload = {
                    "timestamp": timestamp_str,
                    "customer_id": customer_id,
                    "engine": engine_name,
                    "mode": task_type,
                    "input_text": clean_input,
                    "output_text": clean_output
                }
                
                current_namespace = datetime.now().strftime("logs-%Y-%m")
                logger.info(f"🚀 [Background Task] Dispatching vector packet {log_id} to Pinecone index: {PINECONE_INDEX_NAME} (Namespace: {current_namespace})")
                
                index_target = pc_client.Index(PINECONE_INDEX_NAME)
                async_result = index_target.upsert(
                    vectors=[
                        {
                            "id": log_id,
                            "values": vector_values,
                            "metadata": metadata_payload
                        }
                    ],
                    namespace=current_namespace,
                    async_req=True
                )
                async_result.get()
                logger.info(f"✅ [Background Task] Vector transaction successfully committed inside {PINECONE_INDEX_NAME} namespace: {current_namespace}")
        except Exception as pinecone_err:
            logger.error(f"⚠️ Pinecone Background Task Sync Disruption: {str(pinecone_err)}")

# ----------------------------------------------------
# 📡 ROUTING ENDPOINTS & MONITORING TELEMETRY
# ----------------------------------------------------
@app.get("/health", tags=["Monitoring"])
async def system_health_check():
    return {"status": "healthy"}

@app.get("/health/deep", tags=["Monitoring"])
async def deep_health_check():
    checks = {}
    
    try:
        openai_client = gateway_state.get("openai")
        if openai_client:
            await openai_client.models.list(timeout=5.0)
            checks["openai"] = "ok"
        else:
            checks["openai"] = "offline_pool"
    except Exception as err:
        logger.error(f"📡 Deep Probe Fault - OpenAI: {str(err)}")
        checks["openai"] = "unreachable"

    try:
        anthropic_client = gateway_state.get("anthropic")
        if anthropic_client:
            # FIXED TELEMETRY PROBE: Anthropic uses raw un-mapped client timeouts to check connection paths
            await anthropic_client.messages.create(
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
        pc_client = gateway_state.get("pinecone")
        if pc_client:
            pc_client.describe_index(PINECONE_INDEX_NAME)
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


@app.post("/api/claude/chat", tags=["Anthropic Core"])
async def optimized_claude_chat(payload: ChatRequest, background_tasks: BackgroundTasks, customer_id: str = Depends(validate_gateway_token)):
    try:
        client: AsyncAnthropic = gateway_state["anthropic"]
        response = await client.messages.create(
            model=ANTHROPIC_MODEL_NAME,
            max_tokens=1024,
            messages=[{"role": "user", "content": payload.prompt}],
            system="You are an advanced software architect AI. Provide concise answers.",
        )
        # FIXED PARSING CORE: Securely extracts string text fields from modern Anthropic content blocks
        resolved_response = response.content[0].text
        
        background_tasks.add_task(
            append_to_history_log, 
            customer_id, f"Anthropic ({ANTHROPIC_MODEL_NAME})", "Architect Chat Prompt", payload.prompt, resolved_response
        )
        return {"resolved_by": f"Anthropic ({ANTHROPIC_MODEL_NAME})", "response_payload": resolved_response}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail="Chat service unavailable")


@app.post("/api/translate", tags=["OpenAI Core"])
async def optimized_translation(payload: TranslationRequest, background_tasks: BackgroundTasks, customer_id: str = Depends(validate_gateway_token)):
    try:
        client: AsyncOpenAI = gateway_state["openai"]
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": f"Translate the user text into fluent {payload.target_language}."},
                {"role": "user", "content": payload.text},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        transformed_output = content.strip()
        
        background_tasks.add_task(
            append_to_history_log, 
            customer_id, "OpenAI (gpt-4o)", f"Translation ({payload.target_language})", payload.text, transformed_output
        )
        return {"resolved_by": "OpenAI (gpt-4o)", "transformed_text": transformed_output}
    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"❌ Translation Processing Crash Traceback: {str(err)}")
        raise HTTPException(status_code=500, detail="Translation service unavailable")

@app.post("/api/claude/chat", tags=["Anthropic Core"])
async def optimized_claude_chat(payload: ChatRequest, background_tasks: BackgroundTasks, customer_id: str = Depends(validate_gateway_token)):
    try:
        client: AsyncAnthropic = gateway_state["anthropic"]
        response = await client.messages.create(
            model=ANTHROPIC_MODEL_NAME,
            max_tokens=1024,
            messages=[{"role": "user", "content": payload.prompt}],
            system="You are an advanced software architect AI. Provide concise answers.",
        )
        resolved_response = response.content[0].text.strip()
        
        background_tasks.add_task(
            append_to_history_log, 
            customer_id, f"Anthropic ({ANTHROPIC_MODEL_NAME})", "Architect Chat Prompt", payload.prompt, resolved_response
        )
        return {"resolved_by": f"Anthropic ({ANTHROPIC_MODEL_NAME})", "response_payload": resolved_response}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail="Chat service unavailable")

@app.post("/api/logs/search", tags=["Enterprise Log Retrieval"])
async def secure_vector_log_search(payload: LogSearchRequest, customer_id: str = Depends(validate_gateway_token)):
    try:
        openai_client = gateway_state.get("openai")
        pc_client = gateway_state.get("pinecone")
        
        if not openai_client or not pc_client:
            raise HTTPException(status_code=503, detail="Database retrieval connection pool offline")

        embedding_response = await openai_client.embeddings.create(
            input=[payload.query],
            model="text-embedding-3-large",
            dimensions=2048
        )
        query_vector = embedding_response.data[0].embedding
        
        current_namespace = datetime.now().strftime("logs-%Y-%m")
        index_target = pc_client.Index(PINECONE_INDEX_NAME)
        
        search_results = index_target.query(
            vector=query_vector,
            top_k=payload.top_k,
            include_metadata=True,
            namespace=current_namespace,
            filter={"customer_id": {"$eq": customer_id}}
        )
        
        parsed_logs = []
        for match in search_results.get("matches", []):
            parsed_logs.append({
                "log_id": match.get("id"),
                "similarity_score": round(match.get("score", 0), 4),
                "data_payload": match.get("metadata", {})
            })
            
        return {
            "search_query": payload.query,
            "partition_scanned": current_namespace,
            "records_found_count": len(parsed_logs),
            "results": parsed_logs
        }
    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"⚠️ Search Fault Error: {str(err)}")
        raise HTTPException(status_code=500, detail="Log retrieval service unavailable")
@app.post("/api/logs/maintenance/clear-index-cache", tags=["Enterprise Log Management"])
async def force_clean_index_flush(customer_id: str = Depends(validate_gateway_token)):
    """
    Emergency Index Maintenance: Directly flushes the default global namespace 
    to clear out mismatched data fragments on the Pinecone web console grid.
    """
    try:
        pc_client = gateway_state.get("pinecone")
        if pc_client:
            index_target = pc_client.Index(PINECONE_INDEX_NAME)
            
            # 1. Wipes old testing artifacts completely out of the default global namespace
            index_target.delete(delete_all=True, namespace="")
            
            # 2. Refreshes the active monthly bucket
            current_namespace = datetime.now().strftime("logs-%Y-%m")
            
            return {
                "status": "success",
                "message": f"Global default cache namespace flushed cleanly. Active monthly partition '{current_namespace}' preserved."
            }
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Maintenance execution interrupted: {str(err)}")
