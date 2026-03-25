import os
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import Optional

from tools.plan_lookup import run_plan_lookup

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


@app.post("/api/plan-lookup")
async def plan_lookup(file: UploadFile = File(...)):
    """Accept a multipart PDF upload, run the three-layer plan_lookup pipeline,
    and return the structured plan JSON.

    Hard rules enforced here:
    - Only PDF files accepted (basic content-type check)
    - PDF bytes are processed in memory; no PHI is stored server-side
    - Returns 200 with the structured JSON even on partial extraction
    """
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        # Accept octet-stream too since some clients omit the correct MIME type
        ct = file.content_type or ""
        if not ct.endswith("pdf") and ct != "application/octet-stream":
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are accepted. Please upload an SBC PDF.",
            )

    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    result = await run_plan_lookup(pdf_bytes)
    return JSONResponse(content=result)
