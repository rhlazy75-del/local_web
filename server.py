import requests
import threading
import time
import os
from datetime import datetime
from flask import Flask, render_template, jsonify, Response, send_from_directory, request

# ==================== ตั้งค่ากล้อง ====================
CAMERA_IPS = [
    {"id": 1, "ip": "http://10.132.250.222"},
    {"id": 2, "ip": "http://10.132.250.159"},
]

# ==================== ตั้งค่าทั่วไป ====================
SAVE_DIR         = "upload_2cam"
TIMEOUT          = 10
# =======================================================

# ==================== ตั้งค่า Flask ====================
app = Flask(__name__, template_folder='templates')
PORT = 5000
# =======================================================

os.makedirs(SAVE_DIR, exist_ok=True)

# ==================== Capture Loop State ====================
capture_running  = False
capture_thread   = None
capture_interval = 10       # seconds, can be changed via /api/start
# ============================================================


# ──────────────────────────────────────────────────────────
# Capture ONE camera → return result dict
# ──────────────────────────────────────────────────────────
def capture_one(cam: dict, ts: str) -> dict:
    cam_id = cam["id"]
    try:
        resp = requests.get(f"{cam['ip']}/capture", timeout=TIMEOUT)
        if resp.status_code == 200:
            filename = f"cam{cam_id}_{ts}.jpg"
            filepath = os.path.abspath(f"{SAVE_DIR}/{filename}")
            with open(filepath, "wb") as f:
                f.write(resp.content)
            print(f"[cam{cam_id}] ✅ {filename}")
            return {"cam_id": cam_id, "status": "success",
                    "filename": filename, "timestamp": ts}
        return {"cam_id": cam_id, "status": "error",
                "message": f"HTTP {resp.status_code}", "timestamp": ts}
    except requests.exceptions.ConnectionError:
        print(f"[cam{cam_id}] ❌ Offline")
        return {"cam_id": cam_id, "status": "error",
                "message": f"Offline ({cam['ip']})", "timestamp": ts}
    except requests.exceptions.Timeout:
        print(f"[cam{cam_id}] ❌ Timeout")
        return {"cam_id": cam_id, "status": "error",
                "message": f"Timeout ({cam['ip']})", "timestamp": ts}
    except Exception as e:
        return {"cam_id": cam_id, "status": "error",
                "message": str(e), "timestamp": ts}


# ──────────────────────────────────────────────────────────
# Capture ALL cameras in parallel
# ──────────────────────────────────────────────────────────
def capture_all_cameras() -> list:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\n📸 [{ts}]")
    results = [None] * len(CAMERA_IPS)

    def _worker(idx, cam):
        results[idx] = capture_one(cam, ts)

    threads = [threading.Thread(target=_worker, args=(i, cam))
               for i, cam in enumerate(CAMERA_IPS)]
    for t in threads: t.start()
    for t in threads: t.join()
    return results


# ──────────────────────────────────────────────────────────
# Background capture loop
# ──────────────────────────────────────────────────────────
def _capture_loop():
    global capture_running
    while capture_running:
        capture_all_cameras()
        # sleep in 100 ms steps so stop is responsive
        for _ in range(capture_interval * 10):
            if not capture_running:
                break
            time.sleep(0.1)
    print("🛑 Capture loop stopped")


# ══════════════════════════════════════════════════════════
#  Flask Routes
# ══════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')


# ── Live camera proxy ──────────────────────────────────────
@app.route('/image/<int:cam_id>')
def get_image(cam_id):
    cam = next((c for c in CAMERA_IPS if c["id"] == cam_id), None)
    if not cam:
        return "Camera not found", 404
    try:
        resp = requests.get(f"{cam['ip']}/capture", timeout=TIMEOUT)
        if resp.status_code == 200:
            return Response(resp.content, mimetype='image/jpeg')
        return f"Camera HTTP {resp.status_code}", 502
    except requests.exceptions.ConnectionError:
        return "Camera offline", 503
    except requests.exceptions.Timeout:
        return "Camera timeout", 504
    except Exception as e:
        return str(e), 500


# ── Serve saved images from upload_2cam ───────────────────
@app.route('/saved/<path:filename>')
def serve_saved(filename):
    return send_from_directory(os.path.abspath(SAVE_DIR), filename)


# ── START capture loop ────────────────────────────────────
@app.route('/api/start', methods=['POST'])
def api_start():
    global capture_running, capture_thread, capture_interval
    body = request.get_json(silent=True) or {}
    if "interval" in body:
        capture_interval = max(1, int(body["interval"]))

    if capture_running:
        return jsonify({"status": "already_running", "interval": capture_interval})

    capture_running = True
    capture_thread  = threading.Thread(target=_capture_loop, daemon=True)
    capture_thread.start()
    print(f"▶ Started (interval={capture_interval}s)")
    return jsonify({"status": "started", "interval": capture_interval})


# ── STOP capture loop ─────────────────────────────────────
@app.route('/api/stop', methods=['POST'])
def api_stop():
    global capture_running
    capture_running = False
    return jsonify({"status": "stopped"})


# ── Status ────────────────────────────────────────────────
@app.route('/api/status')
def api_status():
    return jsonify({
        "running":  capture_running,
        "interval": capture_interval,
    })


# ── List all saved images from upload_2cam ────────────────
@app.route('/api/images')
def api_images():
    try:
        files = sorted(
            [f for f in os.listdir(SAVE_DIR) if f.lower().endswith('.jpg')],
            reverse=True          # newest first
        )
        items = []
        for f in files:
            # format: cam{id}_{YYYYMMDD_HHMMSS}.jpg
            name  = f.replace('.jpg', '')
            parts = name.split('_', 1)
            try:
                cam_id = int(parts[0].replace('cam', ''))
            except Exception:
                cam_id = 0
            ts = parts[1] if len(parts) > 1 else ''
            items.append({"filename": f, "cam_id": cam_id, "timestamp": ts})
        return jsonify({"images": items, "total": len(items)})
    except Exception as e:
        return jsonify({"images": [], "total": 0, "error": str(e)})


# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 45)
    print("  Dual ESP32-CAM  |  Web Dashboard")
    print(f"  บันทึกที่: ./{SAVE_DIR}/")
    print(f"  🌐 http://localhost:{PORT}")
    print("  Ctrl+C เพื่อหยุด")
    print("=" * 45)
    app.run(host='0.0.0.0', port=PORT, debug=False)