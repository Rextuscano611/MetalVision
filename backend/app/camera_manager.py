import threading
from app.camera_worker import CameraWorker

class CameraManager:
    """Manages all camera workers — add, remove, list, status."""

    def __init__(self):
        self._cameras = {}   # camera_id → { meta + worker }
        self._lock = threading.Lock()
        self._counter = 0

    def add_camera(self, name, rtsp_url, roi=None, source_type=None):
        with self._lock:
            self._counter += 1
            camera_id = f"cam_{self._counter}"

        worker = CameraWorker(
            camera_id=camera_id,
            camera_name=name,
            rtsp_url=rtsp_url,
            roi=roi,
            source_type=source_type
        )
        camera = {
            "id": camera_id,
            "name": name,
            "rtsp_url": rtsp_url,
            "roi": roi,
            "source_type": worker.source_type,
            "worker": worker
        }
        with self._lock:
            self._cameras[camera_id] = camera

        worker.start()
        print(f"Camera added: {camera_id} — {name}")
        return camera_id

    def remove_camera(self, camera_id):
        with self._lock:
            if camera_id not in self._cameras:
                return False
            self._cameras[camera_id]["worker"].stop()
            del self._cameras[camera_id]
        print(f"Camera removed: {camera_id}")
        return True

    def get_all_status(self):
        with self._lock:
            result = []
            for cam in self._cameras.values():
                w = cam["worker"]
                result.append({
                    "id": cam["id"],
                    "name": cam["name"],
                    "rtsp_url": cam["rtsp_url"],
                    "roi": cam["roi"],
                    "source_type": cam.get("source_type", "rtsp"),
                    "status": w.status,
                    "frame_count": w.frame_count,
                    "alert_count": w.alert_count,
                    "progress_pct": getattr(w, "progress_pct", 0)
                })
            return result

    def get_worker(self, camera_id):
        with self._lock:
            cam = self._cameras.get(camera_id)
            return cam["worker"] if cam else None

    def camera_exists(self, camera_id):
        with self._lock:
            return camera_id in self._cameras


# Single shared instance
camera_manager = CameraManager()