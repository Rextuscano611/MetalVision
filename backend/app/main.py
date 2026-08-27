import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.routes import cameras, alerts

app = FastAPI(title="AlertTrace — Metal Detector Monitor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cameras.router, prefix="/api", tags=["cameras"])
app.include_router(alerts.router, prefix="/api", tags=["alerts"])

@app.get("/health")
def health():
    return {"status": "running", "message": "AlertTrace API"}

# Serve the frontend (index.html + any assets) at "/" — same port as the API,
# so the browser sees everything as one origin. Must be mounted LAST so it
# doesn't shadow the /api and /health routes above.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # .../backend/app
_frontend_candidates = [
    os.path.join(BASE_DIR, "..", "..", "frontend"),  # local layout: backend/app -> up 2 -> frontend
    os.path.join(BASE_DIR, "..", "frontend"),          # server layout: app -> up 1 -> frontend
]
FRONTEND_DIR = next(
    (os.path.abspath(p) for p in _frontend_candidates if os.path.isdir(p)),
    None
)

if FRONTEND_DIR:
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    print("WARNING: could not locate frontend/ directory - static files not mounted")