import cv2
import numpy as np

# Tuned from actual footage — do not change without re-testing
RED_LOWER = np.array([155, 100, 210])  # tighter — raised Sat and Val
RED_UPPER = np.array([180, 255, 255])
MIN_RED_PIXELS = 10    # fewer = noise
MAX_RED_PIXELS = 120   # tighter — LED is ~60px, carpet/screen starts much higher
BBOX_PAD = 6            # pixels of padding around the detected blob when drawing a box


def detect_red(frame, roi=None):
    """
    Returns (detected, pixel_count, bbox).
    bbox is (x1, y1, x2, y2) in FULL-FRAME coordinates around the detected red
    blob(s), or None if nothing was detected. Callers use this to draw a
    rectangle on the frame for saved clips / previews.
    """
    if roi:
        x1, y1, x2, y2 = roi
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        region = frame[y1:y2, x1:x2]
        offset_x, offset_y = x1, y1
    else:
        region = frame
        offset_x, offset_y = 0, 0

    if region.size == 0:
        return False, 0, None

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, RED_LOWER, RED_UPPER)
    count = cv2.countNonZero(mask)
    detected = MIN_RED_PIXELS <= count <= MAX_RED_PIXELS

    bbox = None
    if detected:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            # Union bounding box across every red contour found in the region
            rx1 = min(cv2.boundingRect(c)[0] for c in contours)
            ry1 = min(cv2.boundingRect(c)[1] for c in contours)
            rx2 = max(cv2.boundingRect(c)[0] + cv2.boundingRect(c)[2] for c in contours)
            ry2 = max(cv2.boundingRect(c)[1] + cv2.boundingRect(c)[3] for c in contours)
            region_h, region_w = region.shape[:2]
            bbox = (
                offset_x + max(0, rx1 - BBOX_PAD),
                offset_y + max(0, ry1 - BBOX_PAD),
                offset_x + min(region_w, rx2 + BBOX_PAD),
                offset_y + min(region_h, ry2 + BBOX_PAD),
            )

    return detected, count, bbox