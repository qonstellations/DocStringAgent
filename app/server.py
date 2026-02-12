"""FastAPI backend serving the web UI and docstring generation API.

Routes match the frontend expectations:
    GET  /                   → index.html
    GET  /api/ollama-models  → list local Ollama models
    POST /api/generate       → paste-code generation
    POST /api/upload         → file-upload generation
    POST /api/process-path   → server-side path generation
"""

from __future__ import annotations

import ast
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agents import process_file
from app.models import list_ollama_models
from app import config

# ── App Setup ───────────────────────────────────────────────────

app = FastAPI(title="DocStringAgent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


# ── Helpers ─────────────────────────────────────────────────────

def _parse_model_string(model_str: str) -> tuple[str, str]:
    """Parse 'ollama:llama3.2' or 'gemini-2.5-flash' into (provider, model_name)."""
    if model_str.startswith("ollama:"):
        return ("ollama", model_str[len("ollama:"):])
    # Anything else is treated as Gemini
    return ("gemini", model_str)


def _count_elements(source: str) -> int:
    """Count functions and classes in source code."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            count += 1
    return count


# ── Request/Response Models ─────────────────────────────────────

class GenerateRequest(BaseModel):
    source_code: str
    overwrite: bool = False
    model: str = "gemini-2.5-flash"


class PathRequest(BaseModel):
    path: str
    recursive: bool = True
    overwrite: bool = False
    model: str = "gemini-2.5-flash"


# ── API Routes ──────────────────────────────────────────────────

@app.get("/api/ollama-models")
async def get_ollama_models():
    """Return available Ollama models."""
    models = list_ollama_models()
    return {"models": models}


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """Generate docstrings from pasted code."""
    if not req.source_code.strip():
        raise HTTPException(status_code=400, detail="No code provided.")

    provider, model_name = _parse_model_string(req.model)
    start = time.time()

    try:
        result = process_file(
            source=req.source_code,
            provider=provider,
            model_name=model_name,
        )
    except SyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Invalid Python syntax: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    elapsed = round(time.time() - start, 1)
    elements = _count_elements(req.source_code)

    return {
        "original": result["original"],
        "modified": result["documented"],
        "elements_found": elements,
        "docstrings_added": result["functions_processed"],
        "processing_time": elapsed,
    }


@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    overwrite: bool = Form(False),
    model: str = Form("gemini-2.5-flash"),
):
    """Generate docstrings from an uploaded .py file."""
    if not file.filename or not file.filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="Only .py files are supported.")

    content = await file.read()
    source = content.decode("utf-8")
    provider, model_name = _parse_model_string(model)
    start = time.time()

    try:
        result = process_file(
            source=source,
            provider=provider,
            model_name=model_name,
        )
    except SyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Invalid Python syntax: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    elapsed = round(time.time() - start, 1)
    elements = _count_elements(source)

    return {
        "original": source,
        "modified": result["documented"],
        "elements_found": elements,
        "docstrings_added": result["functions_processed"],
        "processing_time": elapsed,
        "filename": file.filename,
    }


@app.post("/api/process-path")
async def process_path(req: PathRequest):
    """Process a file or directory on the server filesystem."""
    target = Path(req.path)

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")

    provider, model_name = _parse_model_string(req.model)
    start = time.time()

    files_to_process: list[Path] = []
    if target.is_file():
        files_to_process = [target]
    elif target.is_dir():
        pattern = "**/*.py" if req.recursive else "*.py"
        files_to_process = sorted(target.glob(pattern))
    else:
        raise HTTPException(status_code=400, detail="Path is neither a file nor a directory.")

    results = []
    total_modified = 0
    total_errors = 0

    for fpath in files_to_process:
        try:
            source = fpath.read_text(encoding="utf-8")
            result = process_file(
                source=source,
                provider=provider,
                model_name=model_name,
            )
            changed = result["functions_processed"] > 0
            if changed:
                total_modified += 1
                if req.overwrite:
                    fpath.write_text(result["documented"], encoding="utf-8")

            results.append({
                "filepath": str(fpath),
                "original": source,
                "modified": result["documented"],
                "elements_found": _count_elements(source),
                "docstrings_added": result["functions_processed"],
                "changed": changed,
            })
        except Exception as e:
            total_errors += 1
            results.append({
                "filepath": str(fpath),
                "original": "",
                "modified": "",
                "elements_found": 0,
                "docstrings_added": 0,
                "changed": False,
                "error": str(e),
            })

    elapsed = round(time.time() - start, 1)

    return {
        "files": results,
        "total_processed": len(files_to_process),
        "total_modified": total_modified,
        "total_errors": total_errors,
        "processing_time": elapsed,
    }


# ── Frontend Serving ────────────────────────────────────────────

@app.get("/favicon.ico")
async def favicon():
    """Suppress 404 for missing favicon."""
    return Response(status_code=204)


@app.get("/")
async def serve_index():
    """Serve the main frontend page."""
    return FileResponse(STATIC_DIR / "index.html")


# Mount static files AFTER explicit routes
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
