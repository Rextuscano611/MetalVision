from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional, List
from app.camera_manager import camera_manager
from app.paths import UPLOADED_VIDEOS_DIR
import cv2
import os
import uuid
import shutil

router = APIRouter()

ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm"}


class AddCameraRequest(BaseModel):
    name: str
    rtsp_url: str
    roi: Optional[List[int]] = None   # [x1, y1, x2, y2]


@router.post("/cameras/add")
def add_camera(req: AddCameraRequest):
    camera_id = camera_manager.add_camera(
        name=req.name,
        rtsp_url=req.rtsp_url,
        roi=req.roi,
        source_type="rtsp"
    )
    return {"message": "Camera added", "camera_id": camera_id}


@router.post("/cameras/upload")
def upload_video(name: str = Form(...), file: UploadFile = File(...)):
    """
    Upload a recorded video (mp4/mov/avi/mkv). It is saved to disk and run
    through the exact same detection + clip-writing pipeline as an RTSP
    camera, except it plays once and then reports status 'completed'
    instead of endlessly retrying like a live stream.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_VIDEO_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXT))}"
        )

    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(UPLOADED_VIDEOS_DIR, safe_name)
    with open(dest_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    camera_id = camera_manager.add_camera(
        name=name,
        rtsp_url=dest_path,
        roi=None,
        source_type="file"
    )
    return {"message": "Video uploaded and processing started", "camera_id": camera_id}


@router.delete("/cameras/{camera_id}")
def remove_camera(camera_id: str):
    if not camera_manager.remove_camera(camera_id):
        raise HTTPException(status_code=404, detail="Camera not found")
    return {"message": f"Camera {camera_id} removed"}


@router.get("/cameras")
def list_cameras():
    return {"cameras": camera_manager.get_all_status()}


@router.get("/cameras/{camera_id}/snapshot")
def get_snapshot(camera_id: str):
    """Returns the latest frame from the camera as a JPEG image."""
    worker = camera_manager.get_worker(camera_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Camera not found")

    frame = worker.get_latest_frame()
    if frame is None:
        raise HTTPException(status_code=503, detail="No frame available yet")

    _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(content=jpeg.tobytes(), media_type="image/jpeg")


@router.put("/cameras/{camera_id}/roi")
def update_roi(camera_id: str, roi: List[int]):
    """Update ROI for an existing camera."""
    worker = camera_manager.get_worker(camera_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Camera not found")
    worker.roi = roi
    return {"message": "ROI updated", "roi": roi}