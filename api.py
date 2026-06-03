# api.py
# FastAPI backend for CS Analyzer.
# Run: python cs_analyzer/api.py
# Or:  uvicorn cs_analyzer.api:app --host 0.0.0.0 --port 8001 --reload

import os
import sys

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from cs_analyzer.analyzer import run_analysis

app = FastAPI(title="CS Analyzer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_DIR = os.path.dirname(os.path.abspath(__file__))
UI_FILE = os.path.join(_DIR, "ui.html")


# ── Models ────────────────────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    doc_no: str
    mode:   str = "purchaser"   # "purchaser" or "cxo"


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
def serve_ui():
    return FileResponse(UI_FILE)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(request: AnalyzeRequest):
    doc_no = request.doc_no.strip()
    if not doc_no:
        raise HTTPException(status_code=400, detail="doc_no is required")
    if request.mode not in ("purchaser", "cxo"):
        raise HTTPException(status_code=400, detail="mode must be 'purchaser' or 'cxo'")
    try:
        insights, token_usage = run_analysis(doc_no, request.mode)
        return {
            "doc_no":      doc_no,
            "mode":        request.mode,
            "insights":    insights,
            "token_usage": token_usage,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port    = int(os.getenv("CS_ANALYZER_PORT", "8001"))
    dev     = os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes")

    print(f"CS Analyzer API  →  http://0.0.0.0:{port}")
    print(f"Mode: {'development (reload on)' if dev else 'production'}\n")

    uvicorn.run(
        "cs_analyzer.api:app",
        host="0.0.0.0",
        port=port,
        reload=dev,          # True only when DEV_MODE=1 in .env
    )
