"""API routes for file uploads.

POST /api/files/upload — Upload a file to the workspace data directory
GET  /api/files — List uploaded files
DELETE /api/files/{filename} — Delete an uploaded file
"""

import logging
import os
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger(__name__)

# Upload directory — files are stored here so agents can access them
UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Max file size: 50MB
MAX_FILE_SIZE = 50 * 1024 * 1024


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file to the workspace.

    Files are stored in data/uploads/ and can be referenced by agents
    using the file_reader tool with the returned path.

    Returns the file path that agents can use.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Sanitize filename — prevent path traversal
    safe_name = os.path.basename(file.filename)
    if not safe_name or safe_name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = UPLOAD_DIR / safe_name

    # Read and save
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE // (1024*1024)}MB)")

    with open(file_path, "wb") as f:
        f.write(content)

    logger.info(f"Uploaded file: {safe_name} ({len(content)} bytes)")

    return {
        "filename": safe_name,
        "path": str(file_path.resolve()),
        "size_bytes": len(content),
        "message": f"File uploaded. Agents can access it at: {file_path.resolve()}",
    }


@router.get("")
async def list_files():
    """List all uploaded files."""
    files = []
    if UPLOAD_DIR.exists():
        for f in UPLOAD_DIR.iterdir():
            if f.is_file():
                files.append({
                    "filename": f.name,
                    "path": str(f.resolve()),
                    "size_bytes": f.stat().st_size,
                })
    return {"files": files, "count": len(files)}


@router.delete("/{filename}")
async def delete_file(filename: str):
    """Delete an uploaded file."""
    safe_name = os.path.basename(filename)
    file_path = UPLOAD_DIR / safe_name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    file_path.unlink()
    logger.info(f"Deleted file: {safe_name}")
    return {"status": "deleted", "filename": safe_name}