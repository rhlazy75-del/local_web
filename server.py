import requests
import threading
import time
import os
from datetime import datetime
from flask import Flask, render_template, jsonify, Response

# ==================== ตั้งค่ากล้อง ====================
CAMERA_IPS = [
    {"id": 1, "ip": "http://10.132.250.222"},
    {"id": 2, "ip": "http://10.132.250.160"},
]

# ==================== ตั้งค่าทั่วไป ====================
SAVE_DIR         = "upload_2cam"
INTERVAL_SECONDS = 10
TIMEOUT          = 10
# =======================================================

# ==================== ตั้งค่า Flask ====================
app = Flask(__name__, template_folder='templates')
PORT = 5000
# =======================================================

os.makedirs(SAVE_DIR, exist_ok=True)


# ==================== Flask Routes ====================
@app.route('/')
def index():
    """แสดงหน้าเว็บหลัก"""
    return render_template('index.html')


@app.route('/image/<int:cam_id>')
def get_image(cam_id):
    """
    Proxy ดึงภาพปัจจุบันจากกล้องโดยตรง แล้วส่งกลับ browser
    ใช้ใน <img src="/image/1"> และ <img src="/image/2">
    """
    cam = next((c for c in CAMERA_IPS if c["id"] == cam_id), None)
    if not cam:
        return "Camera not found", 404

    try:
        resp = requests.get(f"{cam['ip']}/capture", timeout=TIMEOUT)
        if resp.status_code == 200:
            return Response(resp.content, mimetype='image/jpeg')
        else:
            return f"Camera returned HTTP {resp.status_code}", 502
    except requests.exceptions.ConnectionError:
        return "Camera offline", 503
    except requests.exceptions.Timeout:
        return "Camera timeout", 504
    except Exception as e:
        return str(e), 500


@app.route('/capture', methods=['POST'])
def capture_now():
    """
    API endpoint ถ่ายภาพทันทีจากทุกกล้อง บันทึกไฟล์ และส่ง JSON สถานะกลับ
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    camera_results = {}

    def capture_one(cam, ts):
        cam_id = cam["id"]
        try:
            response = requests.get(f"{cam['ip']}/capture", timeout=TIMEOUT)
            if response.status_code == 200:
                filename = f"cam{cam_id}_{ts}.jpg"
                filepath = os.path.abspath(f"{SAVE_DIR}/{filename}")
                with open(filepath, "wb") as f:
                    f.write(response.content)
                camera_results[cam_id] = {
                    "cam_id": cam_id,
                    "status": "success",
                    "filename": filename,
                    "message": f"บันทึกไฟล์สำเร็จ: {filename}"
                }
            else:
                camera_results[cam_id] = {
                    "cam_id": cam_id, "status": "error",
                    "message": f"HTTP {response.status_code}"
                }
        except requests.exceptions.ConnectionError:
            camera_results[cam_id] = {
                "cam_id": cam_id, "status": "error",
                "message": f"เชื่อมต่อไม่ได้ ({cam['ip']})"
            }
        except requests.exceptions.Timeout:
            camera_results[cam_id] = {
                "cam_id": cam_id, "status": "error",
                "message": f"Timeout ({cam['ip']})"
            }
        except Exception as e:
            camera_results[cam_id] = {
                "cam_id": cam_id, "status": "error", "message": str(e)
            }

    threads = [threading.Thread(target=capture_one, args=(cam, timestamp)) for cam in CAMERA_IPS]
    for t in threads: t.start()
    for t in threads: t.join()

    results = list(camera_results.values())
    all_ok = all(r["status"] == "success" for r in results)
    any_ok = any(r["status"] == "success" for r in results)

    return jsonify({
        "timestamp": timestamp,
        "overall": "success" if all_ok else "partial" if any_ok else "error",
        "cameras": results
    })

# =======================================================


def capture_camera(cam: dict, timestamp: str):
    """ดึงภาพจากกล้องตัวเดียว บันทึกไฟล์"""
    cam_id = cam["id"]
    try:
        response = requests.get(f"{cam['ip']}/capture", timeout=TIMEOUT)
        if response.status_code == 200:
            filename = f"cam{cam_id}_{timestamp}.jpg"
            filepath = os.path.abspath(f"{SAVE_DIR}/{filename}")
            with open(filepath, "wb") as f:
                f.write(response.content)
            print(f"[cam{cam_id}] ✅ บันทึกไฟล์: {filepath}")
        else:
            print(f"[cam{cam_id}] ❌ HTTP {response.status_code}")


    except requests.exceptions.ConnectionError:
        print(f"[cam{cam_id}] ❌ เชื่อมต่อไม่ได้ ({cam['ip']})")
    except requests.exceptions.Timeout:
        print(f"[cam{cam_id}] ❌ Timeout ({cam['ip']})")
    except Exception as e:
        print(f"[cam{cam_id}] ❌ Error: {e}")


def capture_all():
    """ดึงภาพจากทุกกล้องพร้อมกันด้วย threading"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\n📸 ถ่ายภาพ [{timestamp}]")
    threads = [threading.Thread(target=capture_camera, args=(cam, timestamp)) for cam in CAMERA_IPS]
    for t in threads: t.start()
    for t in threads: t.join()


def main():
    print("=" * 45)
    print("  Dual ESP32-CAM Capture")
    print(f"  บันทึกที่: ./{SAVE_DIR}/")
    print(f"  ถ่ายทุก {INTERVAL_SECONDS} วินาที")
    print(f"  🌐 เว็บ: http://localhost:{PORT}")
    print("  กด Ctrl+C เพื่อหยุด")
    print("=" * 45)

    web_thread = threading.Thread(
        target=lambda: app.run(host='0.0.0.0', port=PORT, debug=False),
        daemon=True
    )
    web_thread.start()
    print(f"🌐 เซิร์ฟเวอร์เว็บเปิดแล้ว http://localhost:{PORT}\n")

    try:
        while True:
            capture_all()
            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n\n🛑 หยุดการทำงาน")


if __name__ == "__main__":
    main()