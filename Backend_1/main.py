import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Initialize the FastAPI App
app = FastAPI(
    title="Expat AI Starter Backend",
    description="A lightweight, cloud-deployable API layer built in FastAPI.",
    version="1.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define the structure of data incoming from users
class TranslationRequest(BaseModel):
    text: str
    target_language: str

# 1. Health Check / Landing Endpoint
@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "Welcome to your Nomad AI Backend API!",
        "docs_url": "/docs"
    }

# 2. Mock AI Processing Endpoint
@app.post("/api/translate")
async def mock_ai_translation(payload: TranslationRequest):
    if not payload.text:
        # FIXED: Changed status_status_code to status_code
        raise HTTPException(status_code=400, detail="Text string cannot be empty.")
    
    processed_output = f"[Simulated AI Translation to {payload.target_language}]: {payload.text.upper()}"
    
    return {
        "original_text": payload.text,
        "target_language": payload.target_language,
        "ai_output": processed_output,
        "api_key_configured": os.getenv("OPENAI_API_KEY") is not None
    }
