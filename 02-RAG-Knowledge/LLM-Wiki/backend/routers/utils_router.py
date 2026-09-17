"""Utility endpoints — native OS folder picker."""
from __future__ import annotations

import threading
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/utils", tags=["utils"])


def _pick_folder_blocking(result: dict) -> None:
    """Run tkinter dialog on its own thread (must not be called from async context)."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        path = filedialog.askdirectory(parent=root, title="Select folder")
        root.destroy()
        result["path"] = path or ""
    except Exception as exc:
        result["error"] = str(exc)


@router.get("/pick-folder")
def pick_folder() -> JSONResponse:
    """Open a native OS folder-picker dialog and return the selected path."""
    result: dict = {}
    t = threading.Thread(target=_pick_folder_blocking, args=(result,))
    t.start()
    t.join()
    if "error" in result:
        return JSONResponse({"path": "", "error": result["error"]}, status_code=500)
    return JSONResponse({"path": result.get("path", "")})
