"""
ui_app.py — Web UI entry point for the Research Assistant.
 
This module wraps the existing FastAPI app (src/api.py) and mounts the
static HTML UI at /. It does NOT modify api.py or any existing code.
 
Run with:
    uvicorn ui_app:ui_app --host 0.0.0.0 --port 8000 --reload
 
Then open http://localhost:8000 in your browser.
"""
from __future__ import annotations
 
from pathlib import Path
 
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
 
from src.api import app as api_app
 
# Path to the static folder that holds index.html
_STATIC_DIR = Path(__file__).parent / "src" / "static"
 
# Mount static assets (CSS, JS, images) if you add them later
api_app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
 
 
@api_app.get("/", include_in_schema=False)
async def serve_ui(request: Request) -> FileResponse:
    """Serve the single-page Research Assistant UI."""
    return FileResponse(_STATIC_DIR / "index.html")
 
 
# Export under a friendly name so uvicorn can find it
ui_app = api_app