# AlertTrace

A lightweight monitoring system that watches RTSP camera streams (or uploaded video files) for a specific red-LED trigger, records the moment it happens as a short clip, and surfaces it as an alert with a bounding box drawn around the detection.

Built with **FastAPI + OpenCV** on the backend and a single-file **vanilla HTML/JS** dashboard on the frontend.

---

## How it works

1. You add a **source** — either a live RTSP camera URL, or an uploaded video file (mp4/mov/avi/mkv).
2. A background worker (`CameraWorker`) opens the source with OpenCV and reads it frame by frame.
3. Each frame is checked for red pixels in the HSV color space (`colour_detector.py`), optionally restricted to a user-drawn ROI (region of interest).
4. When red is detected:
   - A bounding box is drawn around it (held on-screen for ~1.5s after detection drops out, to avoid flicker).
   - `ClipWriter` starts recording — including a short pre-roll buffer of frames *before* the trigger, so you see the lead-up, not just the moment itself.
   - Once red stops being detected, the clip is finalized and saved to `backend/clips/`, and an alert entry is stored (`alert_store.py`).
5. Live sources (RTSP) reconnect automatically if the stream drops. Uploaded video files are processed once, end to end, then marked `completed`.
6. The frontend polls the backend for camera status + alerts and renders them as cards, with a video player for each saved clip.

---

## Project structure

```
alerttrace/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, static frontend mount
│   │   ├── camera_manager.py    # Tracks all active camera/video workers
│   │   ├── camera_worker.py     # Per-source capture loop, detection, recording state machine
│   │   ├── colour_detector.py   # HSV red-detection + bounding box logic
│   │   ├── clip_writer.py       # Pre-roll buffer + MP4 clip writing
│   │   ├── alert_store.py       # In-memory/records alert metadata
│   │   └── routes/
│   │       ├── cameras.py       # /api/cameras/* — add RTSP, upload video, list, remove
│   │       └── alerts.py        # /api/alerts/*  — list alerts, stream clip files
│   ├── clips/                   # Saved alert clips (gitignored)
│   ├── uploaded_videos/         # Uploaded source videos (gitignored)
│   ├── test_videos/             # Local test footage (gitignored)
│   └── requirements.txt
├── frontend/
│   └── index.html               # Single-file dashboard (no build step)
└── README.md
```

---

## Requirements

- Python 3.10+
- `pip`
- FFmpeg-compatible OpenCV build (already pinned in `requirements.txt`)

---

## Local setup (Windows)

```powershell
git clone <this-repo-url>
cd alerttrace
python -m venv venv
.\venv\Scripts\Activate.ps1
cd backend
pip install -r requirements.txt
```

## Running locally

**Terminal 1 — backend:**
```powershell
cd alerttrace
.\venv\Scripts\Activate.ps1
cd backend
uvicorn app.main:app --reload
```
Backend + dashboard both served at → **http://127.0.0.1:8000**
(the frontend is mounted directly onto the FastAPI app, so there's nothing separate to run)

API docs (auto-generated): **http://127.0.0.1:8000/docs**
Health check: **http://127.0.0.1:8000/health**

---

## Adding a source

**Live camera (RTSP):**
```
POST /api/cameras/add
{ "name": "Room 1", "rtsp_url": "rtsp://user:pass@ip:554/stream", "roi": null }
```

**Uploaded video file:**
```
POST /api/cameras/upload   (multipart/form-data)
  name: "Test clip 1"
  file: <video file>
```
Both are also available from the dashboard UI via the "Live RTSP" / "Upload Video" tabs.

---

## Key API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/cameras/add` | Add an RTSP camera |
| `POST` | `/api/cameras/upload` | Upload and process a video file |
| `GET` | `/api/cameras` | List all sources + live status/progress |
| `DELETE` | `/api/cameras/{id}` | Remove a source and stop its worker |
| `GET` | `/api/alerts` | List all alerts |
| `GET` | `/api/alerts/{id}/clip` | Stream a saved alert clip |
| `GET` | `/health` | Health check |

---

## Deployment

Currently deployed on a Ubuntu server, run as a `systemd` service (`alerttrace.service`) so it survives reboots/crashes, listening on port `8010`. The frontend is served from the same FastAPI app/port — no separate frontend process or port needed.

```bash
systemctl status alerttrace     # check status
systemctl restart alerttrace    # after deploying new code
journalctl -u alerttrace -f     # live logs
```

To deploy a code change: `scp` the changed file(s) to the server, then `systemctl restart alerttrace`.

---

## Notes / gotchas

- `backend/clips/`, `backend/uploaded_videos/`, and `backend/test_videos/` are gitignored — video files are never committed.
- The red-detection HSV thresholds in `colour_detector.py` are tuned against real footage; don't change `RED_LOWER`/`RED_UPPER`/`MIN_RED_PIXELS`/`MAX_RED_PIXELS` without re-testing against known clips.
- RTSP sources retry forever on disconnect; uploaded video sources process once and stop (`status: "completed"`) — they are not meant to loop.
- Traffic between the browser and the server is currently plain HTTP — fine for internal/testing use, but should move to HTTPS before handling anything sensitive.
