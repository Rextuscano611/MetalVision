import cv2
import collections
import threading
import os
import time
import subprocess


class ClipWriter:
    def __init__(self, buffer_sec=10, fps=25, clips_dir="clips"):
        self.buffer_sec = buffer_sec
        self.fps = fps
        self.clips_dir = clips_dir
        os.makedirs(clips_dir, exist_ok=True)

        self.buffer = collections.deque(maxlen=int(buffer_sec * fps))
        self.recording = False
        self.record_frames = []
        self.post_alert_sec = 5
        self.frames_after_red = 0
        self.writer = None
        self.current_clip_path = None
        self._lock = threading.Lock()

    def push_frame(self, frame):
        with self._lock:
            self.buffer.append(frame.copy())

    def start_recording(self, clip_path, frame_size):
        with self._lock:
            if self.recording:
                return
            # Save raw file first with _raw suffix
            self.current_clip_path = clip_path
            raw_path = clip_path.replace('.mp4', '_raw.mp4')
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.writer = cv2.VideoWriter(
                raw_path, fourcc, self.fps,
                (frame_size[1], frame_size[0])
            )
            for f in self.buffer:
                self.writer.write(f)
            self.recording = True
            self.frames_after_red = 0
            print(f"Recording started: {clip_path}")

    def write_frame(self, frame, red_detected):
        with self._lock:
            if not self.recording:
                return
            self.writer.write(frame)
            if not red_detected:
                self.frames_after_red += 1
            else:
                self.frames_after_red = 0

    def should_stop(self):
        with self._lock:
            return self.frames_after_red >= int(self.post_alert_sec * self.fps)

    def stop_recording(self):
        with self._lock:
            if self.writer:
                self.writer.release()
                self.writer = None
            self.recording = False
            final_path = self.current_clip_path
            self.current_clip_path = None

        # Re-encode with FFmpeg for browser compatibility
        raw_path = final_path.replace('.mp4', '_raw.mp4')
        self._reencode(raw_path, final_path)
        return final_path

    def _reencode(self, raw_path, output_path):
        """
        Re-encode with FFmpeg:
        - H.264 video, AAC audio
        - moov atom moved to start (faststart) so browser can seek immediately
        - baseline profile for maximum browser compatibility
        """
        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", raw_path,
                "-c:v", "libx264",
                "-profile:v", "baseline",
                "-level", "3.0",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",   # ← moves moov atom to file start
                "-an",                        # no audio (CCTV usually has none)
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                os.remove(raw_path)  # delete raw file
                print(f"Clip ready: {output_path}")
            else:
                print(f"FFmpeg error: {result.stderr}")
                # Fallback — just rename raw file
                os.rename(raw_path, output_path)
        except Exception as e:
            print(f"FFmpeg not found: {e}")
            os.rename(raw_path, output_path)