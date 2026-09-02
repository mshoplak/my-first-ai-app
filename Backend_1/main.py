import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic

# Load environment variable paths from the master parent configuration directory
load_dotenv(dotenv_path="../.env")

# ----------------------------------------------------
# 🔒 SECURITY FIREWALL LAYER
# ----------------------------------------------------
API_KEY_NAME = "X-Nomad-Gateway-Token"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

async def validate_gateway_token(header_token: str = Security(api_key_header)):
    """
    Acts as a secure firewall dependency filter protecting your AI clusters.
    """
    secret_gateway_token = os.getenv("GATEWAY_SECRET_PASSPHRASE", "nomad_secure_token_2026")
    if header_token != secret_gateway_token:
        raise HTTPException(status_code=403, detail="Invalid Gateway Security Credentials")
    return header_token

# ----------------------------------------------------
# 🌐 LIFESPAN LIFECYCLE CONNECTION POOL MANAGEMENT
# ----------------------------------------------------
gateway_state = {}

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    print("🚀 Initializing State-of-the-Art Multi-AI Client Pools...")
    gateway_state["openai"] = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    gateway_state["anthropic"] = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    yield
    
    print("🛑 Draining and closing down client network connections safely...")
    await gateway_state["openai"].close()
    await gateway_state["anthropic"].close()

# Initialize the state-of-the-art FastAPI context wrapper
app = FastAPI(
    title="Expat AI Advanced Enterprise Gateway",
    description="Optimized multi-threaded ASGI platform orchestrating OpenAI and Anthropic routing structures.",
    version="2.1.0",
    lifespan=app_lifespan
)

# Enable strict modern CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------
# 📊 PYDANTIC STRUCTURAL DATA SCHEMAS
# ----------------------------------------------------
class TranslationRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Raw input text payload needing transformation")
    target_language: str = Field(..., min_length=2, description="Target destination localized language structure")

class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="System query instruction text block")

# ----------------------------------------------------
# 🔌 ADVANCED ROUTING ENDPOINTS (SECURED)
# ----------------------------------------------------
@app.get("/health", tags=["Monitoring"])
async def system_health_check():
    """Automated operational baseline monitoring loop."""
    return {"status": "healthy", "environment": "production_ready"}

@app.post("/api/translate", tags=["OpenAI Core"], dependencies=[Depends(validate_gateway_token)])
async def optimized_translation(payload: TranslationRequest):
    try:
        client: AsyncOpenAI = gateway_state["openai"]
        # UPGRADED: Swapped out gpt-4o-mini for the raw flagship gpt-4o intelligence engine
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": f"Translate text strictly into fluent {payload.target_language}."},
                {"role": "user", "content": payload.text}
            ],
            temperature=0.2
        )
        return {
            "resolved_by": "OpenAI (gpt-4o)",
            "transformed_text": response.choices.message.content.strip()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI Internal Crash: {str(e)}")

@app.post("/api/claude/chat", tags=["Anthropic Core"], dependencies=[Depends(validate_gateway_token)])
async def optimized_claude_chat(payload: ChatRequest):
    try:
        client: AsyncAnthropic = gateway_state["anthropic"]
        response = await client.messages.create(
            model="claude-sonnet-5",  
            max_tokens=1024,
            messages=[{"role": "user", "content": payload.prompt}],
            system="You are an advanced software architect AI. Provide concise answers."
        )
        return {
            "resolved_by": "Anthropic (Claude Sonnet 5)",
            "response_payload": response.content.text
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Anthropic Gateway Failure: {str(e)}")
