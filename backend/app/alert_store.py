import threading
import os
from datetime import datetime


class AlertStore:
    """Thread-safe in-memory store for all alerts across all cameras."""

    def __init__(self):
        self._alerts = []
        self._lock = threading.Lock()

    def add(self, camera_id, camera_name, clip_path, duration_sec, peak_pixels):
        alert = {
            "id": f"alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{camera_id}",
            "camera_id": camera_id,
            "camera_name": camera_name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "clip_path": clip_path,
            "clip_filename": os.path.basename(clip_path),
            "duration_sec": round(duration_sec, 1),
            "peak_pixels": peak_pixels,
            "acknowledged": False,
            "acknowledged_at": None,
        }
        with self._lock:
            self._alerts.insert(0, alert)  # newest first
        print(f"Alert saved: {alert['id']}")
        return alert

    def get_all(self):
        with self._lock:
            return list(self._alerts)

    def delete(self, alert_id):
        with self._lock:
            for i, a in enumerate(self._alerts):
                if a["id"] == alert_id:
                    clip_path = a["clip_path"]
                    self._alerts.pop(i)
                    # Delete the clip file
                    if os.path.exists(clip_path):
                        os.remove(clip_path)
                        print(f"Deleted clip: {clip_path}")
                    return True
        return False

    def acknowledge(self, alert_id):
        """Mark an alert as reviewed. Returns the updated alert dict, or None if not found."""
        with self._lock:
            for a in self._alerts:
                if a["id"] == alert_id:
                    a["acknowledged"] = True
                    a["acknowledged_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    return dict(a)
        return None

    def count(self):
        with self._lock:
            return len(self._alerts)


# Single shared instance
alert_store = AlertStore()