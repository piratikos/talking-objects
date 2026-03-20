#!/usr/bin/env python3
"""
Talking Objects Maker — Flask Web Interface
Upload a machine photo, get talking character prompts + generated images.
API endpoint at /api/generate for programmatic access.
"""

import base64
import io
import json
import os
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from functools import wraps
from threading import Lock

from flask import (Flask, render_template, request, jsonify, send_file,
                   send_from_directory, Response)
from dotenv import load_dotenv
import PIL.Image

load_dotenv()

# Import core logic from CLI tool
from talking_objects import (
    get_client, call_gemini_analysis, generate_image,
    parse_response, load_presets, suggest_preset,
    STYLES, EXPRESSIONS, SYSTEM_PROMPT
)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB
app.config['UPLOAD_FOLDER'] = Path(__file__).parent / 'uploads'
app.config['RESULTS_FOLDER'] = Path(__file__).parent / 'results'

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

# Rate limiting
_rate_lock = Lock()
_rate_log = []  # timestamps of recent requests
RATE_LIMIT = 10  # per minute


def rate_limited(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        with _rate_lock:
            now = time.time()
            _rate_log[:] = [t for t in _rate_log if now - t < 60]
            if len(_rate_log) >= RATE_LIMIT:
                return jsonify({"error": "Rate limit exceeded. Max 10 requests/minute."}), 429
            _rate_log.append(now)
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def prepare_image(image_path_or_file):
    """Load and resize image, return PIL Image."""
    if isinstance(image_path_or_file, (str, Path)):
        img = PIL.Image.open(image_path_or_file)
    else:
        img = PIL.Image.open(image_path_or_file)

    w, h = img.size
    max_edge = 1568
    if max(w, h) > max_edge:
        ratio = max_edge / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), PIL.Image.LANCZOS)

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def process_image(image, style="all", expression="neutral", personality=None, gen_images=True):
    """Core processing: analyze + optionally generate images."""
    client = get_client()
    result = {"status": "processing", "phase": "analysis"}

    # Phase 1: Analysis
    raw = call_gemini_analysis(client, image, personality)
    data = parse_response(raw)
    if data is None:
        return {"status": "error", "message": "Failed to parse AI response", "raw": raw[:500]}

    result["analysis"] = data
    result["prompts"] = data.get("prompts", {})
    result["machine_type"] = data.get("machine_type", "")
    result["personality"] = data.get("personality", "")
    result["catchphrase"] = data.get("catchphrase_gr", "")
    result["face_placement"] = data.get("face_placement", {})
    result["animation_prompt"] = data.get("animation_prompt", "")

    # Preset check
    presets = load_presets()
    preset = suggest_preset(result["machine_type"], presets)
    if preset:
        result["preset"] = preset

    # Phase 2: Image generation
    result["generated_images"] = {}
    if gen_images:
        result["phase"] = "generating"
        gen_styles = STYLES if style == "all" else [style]

        for s in gen_styles:
            prompt = data.get("prompts", {}).get(s, {}).get(expression, "")
            if not prompt:
                continue

            img_data, mime = generate_image(client, image, prompt, s, expression)
            if img_data:
                b64 = base64.b64encode(img_data).decode("utf-8")
                result["generated_images"][f"{s}_{expression}"] = {
                    "data": b64,
                    "mime": mime or "image/png"
                }
            time.sleep(1)  # Rate limit spacing

    result["status"] = "complete"
    result["phase"] = "done"
    return result


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/generate', methods=['POST'])
@rate_limited
def api_generate():
    """API endpoint for programmatic access."""
    if 'image' not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    file = request.files['image']
    if not file or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file. Accepted: jpg, jpeg, png, webp"}), 400

    style = request.form.get('style', 'all')
    expression = request.form.get('expression', 'neutral')
    personality = request.form.get('personality', None)
    gen_images = request.form.get('generate_images', 'true').lower() != 'false'

    try:
        image = prepare_image(file)
        result = process_image(image, style, expression, personality, gen_images)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/upload', methods=['POST'])
@rate_limited
def upload():
    """Web UI upload handler."""
    if 'image' not in request.files:
        return jsonify({"error": "No image"}), 400

    file = request.files['image']
    if not file or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type"}), 400

    style = request.form.get('style', 'all')
    expression = request.form.get('expression', 'neutral')
    personality = request.form.get('personality', '') or None
    gen_images = request.form.get('generate_images', 'true') == 'true'

    # Save upload
    job_id = str(uuid.uuid4())[:8]
    upload_dir = app.config['UPLOAD_FOLDER']
    upload_dir.mkdir(exist_ok=True)

    ext = file.filename.rsplit('.', 1)[1].lower()
    safe_name = f"{job_id}.{ext}"
    upload_path = upload_dir / safe_name
    file.save(str(upload_path))

    try:
        image = prepare_image(upload_path)
        result = process_image(image, style, expression, personality, gen_images)
        result["job_id"] = job_id
        result["original_filename"] = file.filename

        # Save results for download
        results_dir = app.config['RESULTS_FOLDER'] / job_id
        results_dir.mkdir(parents=True, exist_ok=True)

        # Save prompts as files
        for s in STYLES:
            for expr in EXPRESSIONS:
                prompt = result.get("prompts", {}).get(s, {}).get(expr, "")
                if prompt:
                    (results_dir / f"{s}_{expr}.txt").write_text(prompt, encoding="utf-8")

        # Save generated images
        for key, img_info in result.get("generated_images", {}).items():
            ext_img = "png" if "png" in img_info.get("mime", "") else "jpg"
            img_bytes = base64.b64decode(img_info["data"])
            (results_dir / f"{key}.{ext_img}").write_bytes(img_bytes)

        # Save analysis
        analysis = result.get("analysis", {})
        (results_dir / "analysis.json").write_text(
            json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # Clean upload
        if upload_path.exists():
            upload_path.unlink()


@app.route('/download/<job_id>')
def download_all(job_id):
    """Download all results as ZIP."""
    results_dir = app.config['RESULTS_FOLDER'] / job_id
    if not results_dir.exists():
        return jsonify({"error": "Results not found"}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in results_dir.iterdir():
            zf.write(f, f.name)
    buf.seek(0)

    return send_file(buf, mimetype='application/zip',
                     as_attachment=True, download_name=f"talking_objects_{job_id}.zip")


@app.route('/download/<job_id>/<filename>')
def download_file(job_id, filename):
    """Download individual file."""
    results_dir = app.config['RESULTS_FOLDER'] / job_id
    return send_from_directory(str(results_dir), filename, as_attachment=True)


def cleanup_old_results(max_age_hours=24):
    """Remove results older than max_age."""
    for folder in [app.config['RESULTS_FOLDER'], app.config['UPLOAD_FOLDER']]:
        if not folder.exists():
            continue
        for item in folder.iterdir():
            if item.is_dir():
                age = time.time() - item.stat().st_mtime
                if age > max_age_hours * 3600:
                    shutil.rmtree(item, ignore_errors=True)
            elif item.is_file():
                age = time.time() - item.stat().st_mtime
                if age > max_age_hours * 3600:
                    item.unlink(missing_ok=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5050)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()

    app.config['UPLOAD_FOLDER'].mkdir(exist_ok=True)
    app.config['RESULTS_FOLDER'].mkdir(exist_ok=True)
    cleanup_old_results()

    if not args.no_browser:
        import webbrowser
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(f'http://localhost:{args.port}')).start()

    print(f"\n  Talking Objects Maker — Web UI")
    print(f"  http://localhost:{args.port}")
    print(f"  http://0.0.0.0:{args.port} (network)\n")

    app.run(host='0.0.0.0', port=args.port, debug=False)
