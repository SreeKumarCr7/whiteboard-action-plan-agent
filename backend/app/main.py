import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Load AWS credentials from backend/.env (relative to this file).
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from .ocr import (
    OCRBadImageError,
    OCRConfigError,
    OCRServiceError,
    decode_image_from_base64,
    run_textract,
)
from .groq_service import (
    GroqConfigError,
    GroqServiceError,
    clean_notes,
    extract_items,
    synthesize_plan,
)
from .tavily_service import (
    TavilyConfigError,
    TavilyServiceError,
    research_terms,
)

app = FastAPI(
    title="Whiteboard to Action Plan Agent API",
    version="0.1.0",
    description="Turns a whiteboard photo into an editable action plan.",
)

# Allowed origins for the frontend. Comma-separated via the ALLOWED_ORIGINS
# env var (set by the host). Defaults to the local Vite dev server.
_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OCRRequest(BaseModel):
    image: str


class OCRResponse(BaseModel):
    raw_text: str
    lines: list[str]


class CleanNotesRequest(BaseModel):
    raw_text: str


class CleanNotesResponse(BaseModel):
    notes: list[str]


class ExtractItemsRequest(BaseModel):
    notes: list[str]


class ExtractItemsResponse(BaseModel):
    items: list[dict]
    unclear_terms: list[str]


class ResearchTermsRequest(BaseModel):
    terms: list[str]


class SynthesizePlanRequest(BaseModel):
    items: list[dict]
    research_context: dict


@app.get("/")
async def root():
    return {"message": "Hello from the Whiteboard to Action Plan backend"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/ocr", response_model=OCRResponse)
async def ocr(request: OCRRequest):
    try:
        image_bytes = decode_image_from_base64(request.image)
    except OCRBadImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        result = run_textract(image_bytes)
    except OCRConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except OCRServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return result


@app.post("/api/clean-notes", response_model=CleanNotesResponse)
async def clean_notes_endpoint(request: CleanNotesRequest):
    try:
        notes = clean_notes(request.raw_text)
    except GroqConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except GroqServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"notes": notes}


@app.post("/api/extract-items", response_model=ExtractItemsResponse)
async def extract_items_endpoint(request: ExtractItemsRequest):
    try:
        result = extract_items(request.notes)
    except GroqConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except GroqServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return result


@app.post("/api/research-terms")
async def research_terms_endpoint(request: ResearchTermsRequest):
    if not request.terms:
        return {}
    try:
        return research_terms(request.terms)
    except TavilyConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except TavilyServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/synthesize-plan")
async def synthesize_plan_endpoint(request: SynthesizePlanRequest):
    try:
        return synthesize_plan(request.items, request.research_context)
    except GroqConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except GroqServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
