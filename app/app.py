"""
Qobuz-DL Web Queue
------------------
Flask backend with full logging so qobuz-dl errors are always visible.
Check Docker logs with: docker logs -f qobuz-web
"""

import os
import threading
import subprocess
import time
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify

# ── Logging setup — all output goes to stdout (visible in docker logs) ─────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
DOWNLOAD_DIR       = os.environ.get("DOWNLOAD_DIR", "/downloads")
BANDWIDTH_LIMIT_KB = int(os.environ.get("BANDWIDTH_LIMIT_KB", "0"))
DEFAULT_QUALITY    = os.environ.get("DEFAULT_QUALITY", "6")

# ── Queue state ────────────────────────────────────────────────────────────────
queue_lock     = threading.Lock()
download_queue = []
id_counter     = 0
worker_active  = False


def make_entry(item_id, artist):
    return {
        "id":       item_id,
        "artist":   artist,
        "status":   "pending",
        "added":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished": None,
        "output":   "",   # last lines from qobuz-dl, shown in the UI
    }


def build_command(artist):
    """Build the qobuz-dl command, wrapping with trickle if a bandwidth cap is set."""
    qobuz_cmd = [
        "qobuz-dl", "lucky",
        artist,
        "--type", "artist",
        "-d", DOWNLOAD_DIR,
        "-q", DEFAULT_QUALITY,
    ]
    if BANDWIDTH_LIMIT_KB > 0:
        return ["trickle", "-d", str(BANDWIDTH_LIMIT_KB), "-u", "50"] + qobuz_cmd
    return qobuz_cmd


def run_worker():
    """
    Background worker thread.
    Processes one item at a time and logs ALL qobuz-dl output so errors
    are visible via: docker logs -f qobuz-web
    """
    global worker_active

    while True:
        item = None

        with queue_lock:
            for entry in download_queue:
                if entry["status"] == "pending":
                    entry["status"] = "downloading"
                    item = entry
                    break

        if item is None:
            worker_active = False
            return

        # ── Run qobuz-dl and capture everything ───────────────────────────────
        log.info(f"=== Starting download: {item['artist']} ===")
        cmd = build_command(item["artist"])
        log.info(f"Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # merge stderr into stdout so we see it all
                text=True,
                timeout=7200              # 2 hour max per artist
            )
            output  = result.stdout or "(no output)"
            success = (result.returncode == 0)

            # Print every line from qobuz-dl into Docker logs
            for line in output.splitlines():
                log.info(f"[qobuz-dl] {line}")

            if success:
                log.info(f"=== Finished OK: {item['artist']} ===")
            else:
                log.error(f"=== FAILED (exit {result.returncode}): {item['artist']} ===")

        except subprocess.TimeoutExpired:
            output  = "ERROR: Timed out after 2 hours."
            success = False
            log.error(f"Timeout for: {item['artist']}")

        except FileNotFoundError:
            output  = "ERROR: qobuz-dl binary not found. Is it installed?"
            success = False
            log.error(output)

        except Exception as e:
            output  = f"ERROR: {e}"
            success = False
            log.error(f"Exception for {item['artist']}: {e}")

        # ── Update queue entry ─────────────────────────────────────────────────
        with queue_lock:
            item["status"]   = "done" if success else "error"
            item["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            item["output"]   = "\n".join(output.splitlines()[-20:])  # last 20 lines

        time.sleep(1)


def start_worker_if_needed():
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
    global id_counter
    data    = request.get_json() or {}
    raw     = data.get("artists", "").strip()
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
            log.info(f"Queued: {artist} (id={id_counter})")

    start_worker_if_needed()
    return jsonify({"added": added})


@app.route("/queue", methods=["GET"])
def get_queue():
    with queue_lock:
        return jsonify(list(download_queue))


@app.route("/clear-completed", methods=["POST"])
def clear_completed():
    with queue_lock:
        download_queue[:] = [
            e for e in download_queue
            if e["status"] not in ("done", "error")
        ]
    return jsonify({"ok": True})


if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    log.info(f"Download dir : {DOWNLOAD_DIR}")
    log.info(f"Bandwidth cap: {BANDWIDTH_LIMIT_KB} KB/s (0 = off)")
    log.info(f"Quality      : {DEFAULT_QUALITY}")
    app.run(host="0.0.0.0", port=5000, debug=False)
