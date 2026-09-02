import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic  # <-- 1. Import Claude's official client tool

# Load local environment variables from your secure master file one level up
load_dotenv(dotenv_path="../.env")

# Initialize the FastAPI engine
app = FastAPI(
    title="Expat Dual AI Backend",
    description="Multi-model API gateway routing traffic to OpenAI and Claude.",
    version="1.1.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Initialize both AI clients asynchronously using your master key bank
ai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
claude_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Define input structure layout for text processing
class TranslationRequest(BaseModel):
    text: str
    target_language: str

# Define a clean layout structure for a standard Chat query
class ChatRequest(BaseModel):
    prompt: str

# Health / Landing Endpoint
@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "Both OpenAI and Claude engine segments are fully listening!",
        "docs_url": "/docs"
    }

# Endpoint 1: OpenAI Live Translation Routing
@app.post("/api/translate")
async def live_ai_translation(payload: TranslationRequest):
    if not payload.text:
        raise HTTPException(status_code=400, detail="Input text cannot be empty.")
    try:
        response = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"Translate into fluent {payload.target_language}."},
                {"role": "user", "content": payload.text}
            ],
            temperature=0.3
        )
        return {
            "engine": "OpenAI (gpt-4o-mini)",
            "ai_output": response.choices.message.content.strip(),
            "success": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI Failed: {str(e)}")

# Endpoint 2: Claude (Anthropic) Live Chat Routing
@app.post("/api/claude/chat")
async def live_claude_chat(payload: ChatRequest):
    if not payload.prompt:
        raise HTTPException(status_code=400, detail="Prompt string cannot be empty.")
    try:
        # Call the live Anthropic messages engine asynchronously
        response = await claude_client.messages.create(
            model="claude-sonnet-5",  # <-- The correct active model ID
            max_tokens=1024,
            messages=[
                {"role": "user", "content": payload.prompt}
            ],
            system="You are an elite developer assistant. Provide precise, brief answers."
        )
        
        # FIXED: Extract the raw text properly from the nested block structure
        extracted_text = response.content[0].text
        
        return {
            "engine": "Anthropic (Claude 3.5 Haiku)",
            "ai_output": extracted_text,
            "success": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude Transaction Failed: {str(e)}")
