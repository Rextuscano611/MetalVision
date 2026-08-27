import threading
import os
import json
import time
import sqlite3
from datetime import datetime
from app.paths import CLIPS_DIR, DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "alerts.db")
LEGACY_JSON_PATH = os.path.join(CLIPS_DIR, "_alerts_index.json")  # old location, migrated once then renamed aside


class AlertStore:
    """Thread-safe alert store backed by SQLite (stdlib sqlite3 — no extra
    dependency to install).

    Chosen over a flat JSON file for production reliability: a JSON store
    rewrites the ENTIRE file on every single alert, so a crash or power loss
    mid-write can corrupt the whole history at once. SQLite writes are
    transactional, so that failure mode doesn't happen. The public interface
    (add/get_all/delete/acknowledge/count) is unchanged from the old JSON
    version, so nothing elsewhere in the app needed to change.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._init_db()
        self._migrate_legacy_json()

    def _connect(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    camera_id TEXT,
                    camera_name TEXT,
                    timestamp TEXT,
                    clip_path TEXT,
                    clip_filename TEXT,
                    thumbnail_filename TEXT,
                    duration_sec REAL,
                    peak_pixels INTEGER,
                    acknowledged INTEGER,
                    acknowledged_at TEXT,
                    dismissed INTEGER DEFAULT 0,
                    thumbnail_hidden INTEGER DEFAULT 0
                )
            """)
            # Safe to run on every startup: adds columns to a DB created
            # before they existed; no-ops (via the try/except) once already there.
            for _ddl in (
                "ALTER TABLE alerts ADD COLUMN dismissed INTEGER DEFAULT 0",
                "ALTER TABLE alerts ADD COLUMN thumbnail_hidden INTEGER DEFAULT 0",
            ):
                try:
                    conn.execute(_ddl)
                except sqlite3.OperationalError:
                    pass  # column already exists

    def _migrate_legacy_json(self):
        """One-time import of alert history from the old JSON-file store
        (backend/clips/_alerts_index.json), if present, so nothing recorded
        before this change is lost. Safe to run on every startup — does
        nothing once the legacy file has already been migrated away."""
        if not os.path.exists(LEGACY_JSON_PATH):
            return
        try:
            with open(LEGACY_JSON_PATH, "r") as f:
                legacy_alerts = json.load(f)
            with self._connect() as conn:
                for a in legacy_alerts:
                    conn.execute("""
                        INSERT OR IGNORE INTO alerts
                        (id, camera_id, camera_name, timestamp, clip_path, clip_filename,
                         thumbnail_filename, duration_sec, peak_pixels, acknowledged, acknowledged_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        a.get("id"), a.get("camera_id"), a.get("camera_name"), a.get("timestamp"),
                        a.get("clip_path"), a.get("clip_filename"), a.get("thumbnail_filename"),
                        a.get("duration_sec"), a.get("peak_pixels"),
                        1 if a.get("acknowledged") else 0, a.get("acknowledged_at")
                    ))
            os.rename(LEGACY_JSON_PATH, LEGACY_JSON_PATH + ".migrated")
            print(f"Migrated {len(legacy_alerts)} alert(s) from legacy JSON store into SQLite")
        except Exception as e:
            print(f"Legacy alert migration skipped due to error: {e}")

    def _row_to_dict(self, row):
        d = dict(row)
        d["acknowledged"] = bool(d["acknowledged"])
        d["dismissed"] = bool(d.get("dismissed", 0))
        d["thumbnail_hidden"] = bool(d.get("thumbnail_hidden", 0))
        return d

    def add(self, camera_id, camera_name, clip_path, duration_sec, peak_pixels, thumbnail_path=None):
        alert = {
            "id": f"alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{camera_id}",
            "camera_id": camera_id,
            "camera_name": camera_name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "clip_path": clip_path,
            "clip_filename": os.path.basename(clip_path),
            "thumbnail_filename": os.path.basename(thumbnail_path) if thumbnail_path else None,
            "duration_sec": round(duration_sec, 1),
            "peak_pixels": peak_pixels,
            "acknowledged": False,
            "acknowledged_at": None,
        }
        with self._lock:
            with self._connect() as conn:
                conn.execute("""
                    INSERT INTO alerts
                    (id, camera_id, camera_name, timestamp, clip_path, clip_filename,
                     thumbnail_filename, duration_sec, peak_pixels, acknowledged, acknowledged_at, dismissed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    alert["id"], alert["camera_id"], alert["camera_name"], alert["timestamp"],
                    alert["clip_path"], alert["clip_filename"], alert["thumbnail_filename"],
                    alert["duration_sec"], alert["peak_pixels"], 0, None, 0
                ))
        print(f"Alert saved: {alert['id']}")
        return alert

    def get_all(self):
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM alerts ORDER BY timestamp DESC").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete(self, alert_id):
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
                if not row:
                    return False
                a = self._row_to_dict(row)
                conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))

        # File cleanup happens outside the DB lock/transaction, and is
        # best-effort: the alert record is already gone from the database at
        # this point (the source of truth for the dashboard/analytics), so a
        # locked file on Windows (e.g. still being streamed to a <video> tag)
        # must NOT turn into a 500 error for the whole delete request. Retry
        # a few times first since these locks are typically released within
        # a second; if it's still locked after that, log it and move on —
        # the leftover file can be cleaned up later without blocking the UI.
        clip_path = a["clip_path"]
        thumb_filename = a.get("thumbnail_filename")
        self._remove_with_retry(clip_path)
        if thumb_filename:
            thumb_path = os.path.join(os.path.dirname(clip_path), thumb_filename)
            self._remove_with_retry(thumb_path)
        return True

    def _remove_with_retry(self, path, attempts=4, delay_sec=0.4):
        if not path or not os.path.exists(path):
            return
        for attempt in range(attempts):
            try:
                os.remove(path)
                print(f"Deleted: {path}")
                return
            except PermissionError:
                if attempt < attempts - 1:
                    time.sleep(delay_sec)
                else:
                    print(f"WARNING: could not delete {path} — file is locked "
                          f"(likely still open by the browser/streamer). "
                          f"It's now orphaned on disk and can be deleted manually.")

    def acknowledge(self, alert_id):
        """Mark an alert as reviewed. Returns the updated alert dict, or None if not found."""
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE alerts SET acknowledged = 1, acknowledged_at = ? WHERE id = ?",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), alert_id)
                )
                if cur.rowcount == 0:
                    return None
                row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def dismiss(self, alert_id):
        """Hide an alert from the LIVE MONITOR feed only — the record stays in
        the database and keeps counting toward History/analytics. This is
        deliberately non-destructive; true, permanent deletion only happens
        via delete(), which is reserved for the History page. Returns the
        updated alert dict, or None if not found."""
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("UPDATE alerts SET dismissed = 1 WHERE id = ?", (alert_id,))
                if cur.rowcount == 0:
                    return None
                row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def hide_thumbnail(self, alert_id):
        """Hide a thumbnail from the History page's image grid ONLY. Unlike
        delete(), this never touches the alert record, the clip file, or the
        thumbnail file itself — the event still counts fully in every stat
        and chart on the History page. This is purely a display preference
        for decluttering the grid. Returns the updated alert dict, or None
        if not found."""
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("UPDATE alerts SET thumbnail_hidden = 1 WHERE id = ?", (alert_id,))
                if cur.rowcount == 0:
                    return None
                row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def count(self):
        with self._lock:
            with self._connect() as conn:
                return conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]


# Single shared instance
alert_store = AlertStore()
