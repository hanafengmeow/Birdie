import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

app = FastAPI()

origins = [
    "http://localhost:3000",
    os.getenv("FRONTEND_URL", "http://localhost:3000"),
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Location(BaseModel):
    lat: float
    lng: float


class ChatRequest(BaseModel):
    message: str
    plan_json: Optional[dict] = None
    location: Optional[Location] = None
    user_language: str = "en"


async def placeholder_stream():
    yield "Birdie is thinking..."


@app.post("/api/chat")
async def chat(request: ChatRequest):
    return StreamingResponse(placeholder_stream(), media_type="text/plain")
