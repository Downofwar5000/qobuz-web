"""
Qobuz-DL Web Queue
------------------
Flask backend that holds a download queue and runs qobuz-dl
one job at a time using a background worker thread.
"""

import os
import threading
import subprocess
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ── Config from environment variables ─────────────────────────────────────────
DOWNLOAD_DIR       = os.environ.get("DOWNLOAD_DIR", "/downloads")
BANDWIDTH_LIMIT_KB = int(os.environ.get("BANDWIDTH_LIMIT_KB", "0"))  # 0 = off
DEFAULT_QUALITY    = os.environ.get("DEFAULT_QUALITY", "6")


# ── Queue state ────────────────────────────────────────────────────────────────
queue_lock    = threading.Lock()
download_queue = []   # list of entry dicts (see make_entry below)
id_counter    = 0     # auto-incrementing item ID
worker_active = False # is the background worker thread currently running?


def make_entry(item_id, artist):
    """Return a fresh queue entry dict."""
    return {
        "id":       item_id,
        "artist":   artist,
        "status":   "pending",   # pending | downloading | done | error
        "added":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished": None,
    }


def build_command(artist):
    """
    Build the qobuz-dl shell command for an artist name.
    Wraps with trickle when a bandwidth cap is configured.
    """
    qobuz_cmd = [
        "qobuz-dl", "lucky",
        artist,
        "--type", "artist",
        "-d", DOWNLOAD_DIR,
        "-q", DEFAULT_QUALITY,
    ]

    if BANDWIDTH_LIMIT_KB > 0:
        # trickle -d = download KB/s cap, -u = upload KB/s cap
        return ["trickle", "-d", str(BANDWIDTH_LIMIT_KB), "-u", "50"] + qobuz_cmd

    return qobuz_cmd


def run_worker():
    """
    Background worker thread.
    Picks the next pending item, runs qobuz-dl, marks it done/error.
    Exits automatically when the queue is empty.
    """
    global worker_active

    while True:
        item = None

        # Find the next pending item and mark it as downloading
        with queue_lock:
            for entry in download_queue:
                if entry["status"] == "pending":
                    entry["status"] = "downloading"
                    item = entry
                    break

        # Nothing left to do — let the thread die
        if item is None:
            worker_active = False
            return

        # Run the download as a subprocess
        try:
            cmd     = build_command(item["artist"])
            result  = subprocess.run(cmd, capture_output=True, text=True)
            success = (result.returncode == 0)
        except Exception:
            success = False

        # Update the item with its final status
        with queue_lock:
            item["status"]   = "done" if success else "error"
            item["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        time.sleep(1)  # small pause between items


def start_worker_if_needed():
    """Spawn the worker thread if one isn't already running."""
    global worker_active
    if not worker_active:
        worker_active = True
        t = threading.Thread(target=run_worker, daemon=True)
        t.start()


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/add", methods=["POST"])
def add_to_queue():
    """Add one or more artists (newline-separated) to the queue."""
    global id_counter

    data   = request.get_json() or {}
    raw    = data.get("artists", "").strip()
    artists = [line.strip() for line in raw.splitlines() if line.strip()]

    if not artists:
        return jsonify({"error": "No artist names provided"}), 400

    added = []
    with queue_lock:
        for artist in artists:
            id_counter += 1
            entry = make_entry(id_counter, artist)
            download_queue.append(entry)
            added.append({"id": id_counter, "artist": artist})

    start_worker_if_needed()
    return jsonify({"added": added})


@app.route("/queue", methods=["GET"])
def get_queue():
    """Return the full queue as JSON."""
    with queue_lock:
        return jsonify(list(download_queue))


@app.route("/clear-completed", methods=["POST"])
def clear_completed():
    """Remove done/error entries from the queue."""
    with queue_lock:
        download_queue[:] = [
            e for e in download_queue
            if e["status"] not in ("done", "error")
        ]
    return jsonify({"ok": True})


if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=False)
