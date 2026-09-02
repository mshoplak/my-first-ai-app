import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import AsyncOpenAI

# 1. Look one directory up (..) for your master unified keys
load_dotenv(dotenv_path="../.env")

# 2. Initialize the FastAPI engine
app = FastAPI(
    title="Expat AI Live Backend",
    description="A fully connected, cloud-deployable API layer talking to live LLMs.",
    version="1.0.0"
)

# 3. Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Initialize the asynchronous OpenAI client wrapper
ai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Define input structure layout
class TranslationRequest(BaseModel):
    text: str
    target_language: str

# 1. Health / Landing Endpoint
@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "Your live Nomad AI API is fully listening!",
        "docs_url": "/docs"
    }

# 2. Real Live AI Translation & Processing Endpoint
@app.post("/api/translate")
async def live_ai_translation(payload: TranslationRequest):
    if not payload.text:
        raise HTTPException(status_code=400, detail="Input text cannot be empty.")
    
    try:
        # Call the live OpenAI completion engine asynchronously
        response = await ai_client.chat.completions.create(
            model="gpt-4o-mini",  # Blazing-fast, highly cost-efficient model
            messages=[
                {
                    "role": "system", 
                    "content": f"You are an expert translator. Translate the following text directly into fluent {payload.target_language}. Respond ONLY with the direct translation text."
                },
                {"role": "user", "content": payload.text}
            ],
            temperature=0.3
        )
        
        # Extract the processed message string payload
        translated_output = response.choices[0].message.content.strip()
        
        return {
            "original_text": payload.text,
            "target_language": payload.target_language,
            "ai_output": translated_output,
            "success": True
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API Transaction Failed: {str(e)}")
