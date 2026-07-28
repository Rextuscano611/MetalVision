import cv2
import threading
import time
import os
from datetime import datetime
from app.colour_detector import detect_red
from app.clip_writer import ClipWriter
from app.alert_store import alert_store

CLIPS_DIR = "clips"


class CameraWorker:
    """
    One thread per camera.
    Continuously reads RTSP stream, detects red LED, saves clips on alert.
    """

    def __init__(self, camera_id, camera_name, rtsp_url, roi=None):
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.rtsp_url = rtsp_url
        self.roi = roi           # [x1, y1, x2, y2] or None

        self.status = "connecting"   # connecting | active | disconnected | stopped
        self.frame_count = 0
        self.alert_count = 0
        self._stop_event = threading.Event()
        self._thread = None
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self.clip_writer = ClipWriter(
            buffer_sec=5,
            clips_dir=CLIPS_DIR
        )

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self.status = "stopped"

    def get_latest_frame(self):
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def _run(self):
        while not self._stop_event.is_set():
            # Support webcam testing — pass "webcam" or "0" as URL
            if self.rtsp_url in ("webcam", "0"):
                cap = cv2.VideoCapture(0)
            else:
                cap = cv2.VideoCapture(self.rtsp_url)

            if not cap.isOpened():
                self.status = "disconnected"
                print(f"[{self.camera_id}] Cannot open stream. Retrying in 5s...")
                time.sleep(5)
                continue

            fps = cap.get(cv2.CAP_PROP_FPS) or 25
            self.clip_writer.fps = fps
            self.status = "active"
            print(f"[{self.camera_id}] Stream opened at {fps:.0f}fps")

            red_detected_prev = False
            alert_start_time = None
            peak_pixels = 0
            clip_path = None

            while not self._stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    print(f"[{self.camera_id}] Stream lost. Reconnecting...")
                    self.status = "disconnected"
                    break

                self.frame_count += 1

                # Store latest frame for snapshot endpoint
                with self._frame_lock:
                    self._latest_frame = frame.copy()

                # Push to rolling buffer
                self.clip_writer.push_frame(frame)

                # Detect red LED
                red_now, pixel_count = detect_red(frame, self.roi)

                # ── Alert state machine ──────────────────
                if red_now and not red_detected_prev:
                    # Red JUST started — begin recording
                    alert_start_time = time.time()
                    peak_pixels = pixel_count
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    clip_path = os.path.join(
                        CLIPS_DIR,
                        f"alert_{ts}_{self.camera_id}.mp4"
                    )
                    self.clip_writer.start_recording(clip_path, frame.shape)
                    self.clip_writer.write_frame(frame, red_now)

                elif red_now and red_detected_prev:
                    # Red is CONTINUING — keep writing
                    peak_pixels = max(peak_pixels, pixel_count)
                    self.clip_writer.write_frame(frame, red_now)

                    alert_duration = time.time() - alert_start_time
                    if alert_duration > 30:
                        # Hit max duration — force save
                        saved_path = self.clip_writer.stop_recording()
                        alert_store.add(
                            camera_id=self.camera_id,
                            camera_name=self.camera_name,
                            clip_path=saved_path,
                            duration_sec=alert_duration,
                            peak_pixels=peak_pixels
                        )
                        self.alert_count += 1
                        alert_start_time = None
                        peak_pixels = 0
                        red_detected_prev = False
                        continue

                elif not red_now and self.clip_writer.recording:
                    # Red STOPPED — write post-alert frames and check if done
                    self.clip_writer.write_frame(frame, red_now)

                    if self.clip_writer.should_stop():
                        alert_duration = time.time() - alert_start_time
                        saved_path = self.clip_writer.stop_recording()
                        alert_store.add(
                            camera_id=self.camera_id,
                            camera_name=self.camera_name,
                            clip_path=saved_path,
                            duration_sec=alert_duration,
                            peak_pixels=peak_pixels
                        )
                        self.alert_count += 1
                        alert_start_time = None
                        peak_pixels = 0

                red_detected_prev = red_now

            cap.release()
            if not self._stop_event.is_set():
                time.sleep(3)  # wait before reconnect attempt

        print(f"[{self.camera_id}] Worker stopped.")