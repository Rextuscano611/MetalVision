from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional, List
from app.camera_manager import camera_manager
import cv2

router = APIRouter()


class AddCameraRequest(BaseModel):
    name: str
    rtsp_url: str
    roi: Optional[List[int]] = None   # [x1, y1, x2, y2]


@router.post("/cameras/add")
def add_camera(req: AddCameraRequest):
    camera_id = camera_manager.add_camera(
        name=req.name,
        rtsp_url=req.rtsp_url,
        roi=req.roi
    )
    return {"message": "Camera added", "camera_id": camera_id}


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