from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

@app.get("/")
def root():
    return {"status": "running", "message": "AlertTrace API"}