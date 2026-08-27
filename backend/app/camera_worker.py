import cv2
import threading
import time
import os
import math
import numpy as np
from datetime import datetime
from app.colour_detector import detect_red
from app.clip_writer import ClipWriter
from app.alert_store import alert_store
from app.paths import CLIPS_DIR

BBOX_HOLD_SEC = 1.5   # keep showing the last box this long after detection drops out,
                      # so it doesn't flicker on/off between frames


def _annotate_frame(frame, roi=None, bbox=None, t=0.0):
    """Draws the ROI outline (thin gray, if set). When a detection (or a held
    detection, see BBOX_HOLD_SEC) is active, also draws a high-visibility
    alert overlay that's impossible to miss at a glance:
      1. A pulsing red border around the ENTIRE frame
      2. A bold translucent banner across the top with a warning icon + text
      3. A precise box on the exact detected pixels
    `t` is elapsed VIDEO time in seconds (frame_count / fps), not wall-clock —
    that keeps the pulse animating at a consistent visual rate whether this is
    a live RTSP feed or an uploaded file being processed faster than real-time.
    Mutates and returns the frame in place.
    """
    h, w = frame.shape[:2]

    if roi:
        rx1, ry1, rx2, ry2 = roi
        cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), (150, 150, 150), 1)

    if not bbox:
        return frame

    bx1, by1, bx2, by2 = bbox
    red = (0, 0, 255)

    # Pulse 0..1, ~2 cycles/sec of video time
    pulse = (math.sin(t * 2 * math.pi * 2) + 1) / 2

    # 1) Full-frame pulsing border — the whole footage "flashes" red
    border = int(8 + pulse * 10)
    cv2.rectangle(frame, (0, 0), (w - 1, h - 1), red, border)

    # 2) Bold translucent banner across the top
    banner_h = max(46, h // 10)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, banner_h), red, -1)
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

    # Warning-triangle icon on the left of the banner
    icon_cx, icon_cy = banner_h // 2 + 12, banner_h // 2
    icon_size = int(banner_h * 0.32)
    tri = np.array([
        [icon_cx, icon_cy - icon_size],
        [icon_cx - icon_size, icon_cy + icon_size],
        [icon_cx + icon_size, icon_cy + icon_size]
    ], np.int32)
    cv2.polylines(frame, [tri], True, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.line(frame, (icon_cx, icon_cy - icon_size // 3), (icon_cx, icon_cy + icon_size // 6), (255, 255, 255), 3)
    cv2.circle(frame, (icon_cx, icon_cy + icon_size // 2 + 2), 3, (255, 255, 255), -1)

    label = "METAL DETECTED"
    font_scale = banner_h / 50.0
    cv2.putText(frame, label, (icon_cx + icon_size + 15, int(banner_h * 0.68)),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), 3, cv2.LINE_AA)

    # 3) Precise box on the exact detected pixels
    cv2.rectangle(frame, (bx1, by1), (bx2, by2), red, 3)

    return frame


class CameraWorker:
    """
    One thread per camera.
    Continuously reads RTSP stream, detects red LED, saves clips on alert.
    """

    def __init__(self, camera_id, camera_name, rtsp_url, roi=None, source_type=None):
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.rtsp_url = rtsp_url
        self.roi = roi           # [x1, y1, x2, y2] or None

        # source_type: "rtsp" (live stream, reconnect forever) or "file" (uploaded video,
        # process once then stop). Auto-detect if not explicitly given.
        if source_type is None:
            source_type = "file" if os.path.isfile(rtsp_url) else "rtsp"
        self.source_type = source_type

        self.status = "connecting"   # connecting | active | disconnected | stopped | completed
        self.frame_count = 0
        self.alert_count = 0
        self.progress_pct = 0        # 0-100, only meaningful for file sources
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

    def _save_thumbnail(self, frame, clip_path):
        """Save the peak-detection frame (already has the full alert overlay
        baked in) as a JPEG next to the clip, used as the video poster/thumbnail
        in the dashboard's alert list so the striking frame is visible before
        anyone even clicks play."""
        thumb_path = clip_path.replace(".mp4", "_thumb.jpg")
        try:
            cv2.imwrite(thumb_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return thumb_path
        except Exception as e:
            print(f"[{self.camera_id}] Failed to save thumbnail: {e}")
            return None

    def _run(self):
        while not self._stop_event.is_set():
            # Support webcam testing — pass "webcam" or "0" as URL
            if self.rtsp_url in ("webcam", "0"):
                cap = cv2.VideoCapture(0)
            else:
                cap = cv2.VideoCapture(self.rtsp_url)

            if not cap.isOpened():
                self.status = "disconnected"
                if self.source_type == "file":
                    print(f"[{self.camera_id}] Cannot open video file. Stopping.")
                    self.status = "stopped"
                    return
                print(f"[{self.camera_id}] Cannot open stream. Retrying in 5s...")
                time.sleep(5)
                continue

            fps = cap.get(cv2.CAP_PROP_FPS) or 25
            self.clip_writer.fps = fps
            self.status = "active"
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if self.source_type == "file" else 0
            bbox_hold_frames = max(1, int(fps * BBOX_HOLD_SEC))
            print(f"[{self.camera_id}] {'File' if self.source_type == 'file' else 'Stream'} opened at {fps:.0f}fps")

            red_detected_prev = False
            alert_start_time = None
            peak_pixels = 0
            peak_frame = None
            clip_path = None
            last_bbox = None
            bbox_hold_counter = 0

            while not self._stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    if self.source_type == "file":
                        print(f"[{self.camera_id}] End of video reached.")
                    else:
                        print(f"[{self.camera_id}] Stream lost. Reconnecting...")
                        self.status = "disconnected"
                    break

                self.frame_count += 1
                if self.source_type == "file" and total_frames:
                    self.progress_pct = min(100, round(100 * self.frame_count / total_frames))

                # Store latest frame for snapshot endpoint
                with self._frame_lock:
                    self._latest_frame = frame.copy()

                # Push to rolling buffer
                self.clip_writer.push_frame(frame)

                # Detect red LED
                red_now, pixel_count, bbox = detect_red(frame, self.roi)

                # Keep the box on screen for a bit after detection drops out for a
                # frame or two, so it doesn't flicker — pure visual smoothing, does
                # NOT affect red_now / the alert state machine below.
                if bbox:
                    last_bbox = bbox
                    bbox_hold_counter = bbox_hold_frames
                    display_bbox = bbox
                elif bbox_hold_counter > 0:
                    bbox_hold_counter -= 1
                    display_bbox = last_bbox
                else:
                    display_bbox = None

                # Draw ROI outline / detection box directly onto the frame so it's
                # baked into whatever gets written to the alert clip below.
                _annotate_frame(frame, self.roi, display_bbox, t=self.frame_count / fps)

                # ── Alert state machine ──────────────────
                if red_now and not red_detected_prev:
                    # Red JUST started — begin recording
                    alert_start_time = time.time()
                    peak_pixels = pixel_count
                    peak_frame = frame.copy()
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    clip_path = os.path.join(
                        CLIPS_DIR,
                        f"alert_{ts}_{self.camera_id}.mp4"
                    )
                    self.clip_writer.start_recording(clip_path, frame.shape)
                    self.clip_writer.write_frame(frame, red_now)

                elif red_now and red_detected_prev:
                    # Red is CONTINUING — keep writing
                    if pixel_count > peak_pixels:
                        peak_pixels = pixel_count
                        peak_frame = frame.copy()
                    self.clip_writer.write_frame(frame, red_now)

                    alert_duration = time.time() - alert_start_time
                    if alert_duration > 30:
                        # Hit max duration — force save
                        saved_path = self.clip_writer.stop_recording()
                        thumb_path = self._save_thumbnail(peak_frame, saved_path) if peak_frame is not None else None
                        alert_store.add(
                            camera_id=self.camera_id,
                            camera_name=self.camera_name,
                            clip_path=saved_path,
                            duration_sec=alert_duration,
                            peak_pixels=peak_pixels,
                            thumbnail_path=thumb_path
                        )
                        self.alert_count += 1
                        alert_start_time = None
                        peak_pixels = 0
                        peak_frame = None
                        red_detected_prev = False
                        continue

                elif not red_now and self.clip_writer.recording:
                    # Red STOPPED — write post-alert frames and check if done
                    self.clip_writer.write_frame(frame, red_now)

                    if self.clip_writer.should_stop():
                        alert_duration = time.time() - alert_start_time
                        saved_path = self.clip_writer.stop_recording()
                        thumb_path = self._save_thumbnail(peak_frame, saved_path) if peak_frame is not None else None
                        alert_store.add(
                            camera_id=self.camera_id,
                            camera_name=self.camera_name,
                            clip_path=saved_path,
                            duration_sec=alert_duration,
                            peak_pixels=peak_pixels,
                            thumbnail_path=thumb_path
                        )
                        self.alert_count += 1
                        alert_start_time = None
                        peak_pixels = 0
                        peak_frame = None

                red_detected_prev = red_now

            cap.release()

            if self.source_type == "file":
                # Video ended (or file couldn't be read past this point) — flush any
                # in-progress recording, then stop for good. Don't loop/retry like RTSP.
                if self.clip_writer.recording:
                    alert_duration = time.time() - alert_start_time
                    saved_path = self.clip_writer.stop_recording()
                    thumb_path = self._save_thumbnail(peak_frame, saved_path) if peak_frame is not None else None
                    alert_store.add(
                        camera_id=self.camera_id,
                        camera_name=self.camera_name,
                        clip_path=saved_path,
                        duration_sec=alert_duration,
                        peak_pixels=peak_pixels,
                        thumbnail_path=thumb_path
                    )
                    self.alert_count += 1
                self.progress_pct = 100
                if not self._stop_event.is_set():
                    self.status = "completed"
                return

            if not self._stop_event.is_set():
                time.sleep(3)  # wait before reconnect attempt

        print(f"[{self.camera_id}] Worker stopped.")