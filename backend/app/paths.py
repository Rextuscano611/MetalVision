"""
Central, absolute path definitions for every persistent data folder the app
uses (clips, thumbnails, uploaded videos, the SQLite alert database).

WHY THIS FILE EXISTS: every one of these used to be a bare relative string
like "clips" or "data", which resolves relative to whatever directory
`uvicorn` happened to be launched FROM — not the project's actual location.
That "worked" only by convention (always `cd backend` first), and broke
silently and confusingly at least twice already:
  1. `StaticFiles(directory="frontend")` failed outright when run locally
     because the local convention (`cd backend`) put the process one level
     deeper than the relative path expected.
  2. The SQLite alert database appeared to "reset to empty" because a new,
     empty database was silently created at a different resolved location
     than the one from a previous session.

Fix: resolve every path from THIS file's own location on disk (which never
moves), not from the current working directory (which can vary run to run).
"""

import os

_APP_DIR = os.path.dirname(os.path.abspath(__file__))          # .../backend/app
BACKEND_DIR = os.path.abspath(os.path.join(_APP_DIR, ".."))    # .../backend

CLIPS_DIR = os.path.join(BACKEND_DIR, "clips")
DATA_DIR = os.path.join(BACKEND_DIR, "data")
UPLOADED_VIDEOS_DIR = os.path.join(BACKEND_DIR, "uploaded_videos")

for _d in (CLIPS_DIR, DATA_DIR, UPLOADED_VIDEOS_DIR):
    os.makedirs(_d, exist_ok=True)

# Printed once at import time so a future "where did my data go" question can
# be answered by just looking at the startup log instead of guessing.
print(f"[paths] BACKEND_DIR = {BACKEND_DIR}")
print(f"[paths] CLIPS_DIR   = {CLIPS_DIR}")
print(f"[paths] DATA_DIR    = {DATA_DIR}")
