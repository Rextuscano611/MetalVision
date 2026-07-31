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
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")