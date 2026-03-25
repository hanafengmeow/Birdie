import os
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import Optional

from agents.birdie_agent import run_birdie_agent
from tools.care_router import run_care_router
from tools.find_care import run_find_care
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


class CareRouterRequest(BaseModel):
    user_message: str
    extracted_context: Optional[dict] = None
    plan_json: Optional[dict] = None
    user_language: str = "en"


class FindCareRequest(BaseModel):
    care_type: str
    location: Location
    open_now: bool = True
    plan_json: Optional[dict] = None
    user_language: str = "en"


@app.post("/api/chat")
async def chat(request: ChatRequest):
    return StreamingResponse(run_birdie_agent(request), media_type="text/plain")


@app.post("/api/care-router")
async def care_router_endpoint(request: CareRouterRequest):
    """Route a symptom description to the appropriate care setting.

    Hard rules enforced:
    - NEVER diagnoses conditions or recommends specific treatments
    - NEVER confirms in-network status — always "call to verify"
    - ALWAYS returns the disclaimer in every response
    - plan_json=null handled gracefully with general guidance
    """
    result = await run_care_router(
        user_message=request.user_message,
        extracted_context=request.extracted_context,
        plan_json=request.plan_json,
        user_language=request.user_language,
    )
    return JSONResponse(content=result)


@app.post("/api/find-care")
async def find_care_endpoint(request: FindCareRequest):
    """Find nearby providers for a given care_type.

    Hard rules enforced:
    - network_status always "verify_required" — never confirms in-network status
    - Telehealth special case skips Maps entirely
    - No Maps results or API failure → telehealth fallback with insurer URL
    - plan_json=null handled gracefully
    """
    result = await run_find_care(
        care_type=request.care_type,
        location={"lat": request.location.lat, "lng": request.location.lng},
        open_now=request.open_now,
        plan_json=request.plan_json,
        user_language=request.user_language,
    )
    return JSONResponse(content=result)


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
