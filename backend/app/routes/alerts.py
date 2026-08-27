from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from app.alert_store import alert_store
from app.paths import CLIPS_DIR
import os

router = APIRouter()


class AckRequest(BaseModel):
    acknowledged: bool = True


@router.get("/alerts")
def get_alerts():
    return {
        "count": alert_store.count(),
        "alerts": alert_store.get_all()
    }


@router.get("/alerts/clip/{filename}")
def get_clip(filename: str, request: Request):
    clip_path = os.path.join(CLIPS_DIR, filename)
    if not os.path.exists(clip_path):
        raise HTTPException(status_code=404, detail="Clip not found")

    file_size = os.path.getsize(clip_path)
    range_header = request.headers.get("Range")

    if range_header:
        range_val = range_header.strip().replace("bytes=", "")
        parts = range_val.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        end = min(end, file_size - 1)
        content_length = end - start + 1

        def iter_file(path, s, length, chunk=256*1024):
            with open(path, "rb") as f:
                f.seek(s)
                remaining = length
                while remaining > 0:
                    data = f.read(min(chunk, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return StreamingResponse(
            iter_file(clip_path, start, content_length),
            status_code=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Type": "video/mp4",
            },
            media_type="video/mp4"
        )

    return FileResponse(
        clip_path,
        media_type="video/mp4",
        headers={"Accept-Ranges": "bytes"}
    )


@router.get("/alerts/thumbnail/{filename}")
def get_thumbnail(filename: str):
    thumb_path = os.path.join(CLIPS_DIR, filename)
    if not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(thumb_path, media_type="image/jpeg")


@router.patch("/alerts/{alert_id}/ack")
def acknowledge_alert(alert_id: str, req: AckRequest):
    alert = alert_store.acknowledge(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.patch("/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: str):
    """Hides the alert from the live monitor feed only. It stays in the
    database and keeps counting toward the History page's analytics — use
    DELETE /alerts/{id} instead for permanent removal."""
    alert = alert_store.dismiss(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.patch("/alerts/{alert_id}/hide-thumbnail")
def hide_thumbnail(alert_id: str):
    """Hides the thumbnail from the History page's image grid ONLY. The
    event record, clip file, and thumbnail file are all left untouched, so
    every stat and chart on the History page still counts it — this is a
    display-only preference, not a deletion."""
    alert = alert_store.hide_thumbnail(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: str):
    deleted = alert_store.delete(alert_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"message": "Alert deleted"}