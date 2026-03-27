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
    plan_raw_text: Optional[str] = None
    location: Optional[Location] = None
    user_language: str = "en"
    conversation_history: Optional[list[dict]] = None


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


class GeocodeRequest(BaseModel):
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


@app.post("/api/geocode")
async def geocode_address(request: GeocodeRequest):
    """Convert a text address to lat/lng or reverse-geocode lat/lng to an address.

    Two modes:
    - Forward: provide `address` -> returns lat, lng, formatted_address
    - Reverse: provide `lat` and `lng` (address empty/None) -> returns lat, lng, formatted_address
    """
    import googlemaps

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Geocoding service unavailable.")

    reverse_mode = (
        request.lat is not None
        and request.lng is not None
        and not (request.address and request.address.strip())
    )

    if not reverse_mode and not (request.address and request.address.strip()):
        raise HTTPException(
            status_code=400,
            detail="Provide either an address or lat/lng coordinates.",
        )

    try:
        gmaps = googlemaps.Client(key=api_key)

        if reverse_mode:
            results = gmaps.reverse_geocode((request.lat, request.lng))
            if not results:
                raise HTTPException(status_code=404, detail="Address not found for these coordinates.")
            return JSONResponse(content={
                "lat": request.lat,
                "lng": request.lng,
                "formatted_address": results[0].get("formatted_address", ""),
            })
        else:
            results = gmaps.geocode(request.address)
            if not results:
                raise HTTPException(status_code=404, detail="Address not found.")
            loc = results[0]["geometry"]["location"]
            return JSONResponse(content={
                "lat": loc["lat"],
                "lng": loc["lng"],
                "formatted_address": results[0].get("formatted_address", request.address),
            })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
