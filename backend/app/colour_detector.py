import cv2
import numpy as np

# Tuned from actual footage — do not change without re-testing
RED_LOWER = np.array([155, 100, 210])  # tighter — raised Sat and Val
RED_UPPER = np.array([180, 255, 255])
MIN_RED_PIXELS = 10    # fewer = noise
MAX_RED_PIXELS = 120   # tighter — LED is ~60px, carpet/screen starts much higher


def detect_red(frame, roi=None):
    if roi:
        x1, y1, x2, y2 = roi
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        region = frame[y1:y2, x1:x2]
    else:
        region = frame

    if region.size == 0:
        return False, 0

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, RED_LOWER, RED_UPPER)
    count = cv2.countNonZero(mask)
    detected = MIN_RED_PIXELS <= count <= MAX_RED_PIXELS
    return detected, count