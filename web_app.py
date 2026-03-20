#!/usr/bin/env python3
"""
Talking Objects Maker v2 — Flask Web Interface
Upload photo → analyze → generate images → regenerate with different settings.
Session gallery keeps all generated images. API at /api/generate.
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
                   send_from_directory, session)
from dotenv import load_dotenv
import PIL.Image

load_dotenv()

from talking_objects import (
    get_client, call_gemini_analysis, generate_image, _short_prompt,
    parse_response, load_presets, suggest_preset,
    STYLES, EXPRESSIONS
)

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET", "toolgini-talking-objects-2026")
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = Path(__file__).parent / 'uploads'
app.config['RESULTS_FOLDER'] = Path(__file__).parent / 'results'

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
BODY_STYLES = ['face_only', 'face_arms', 'face_arms_legs', 'face_wheels']

_rate_lock = Lock()
_rate_log = []
RATE_LIMIT = 10

BODY_PROMPTS = {
    "face_only": "",
    "face_arms": (
        "Also add small cartoon robot-style arms to the machine. "
        "Thin metallic mechanical appendages from the sides with 3-fingered hands. "
        "Arms match the machine color scheme. Wall-E style — simple, charming, mechanical. "
        "Machine body shape and proportions must NOT change."
    ),
    "face_arms_legs": (
        "Also add small cartoon robot-style arms and legs to the machine. "
        "Arms: thin metallic appendages from the sides with 3-fingered hands. "
        "Legs: short sturdy mechanical legs at the bottom so the machine can stand. "
        "Arms and legs match machine color — metallic, industrial. Wall-E style. "
        "Machine body shape must NOT change."
    ),
    "face_wheels": (
        "Also add small cartoon wheels at the bottom of the machine so it looks mobile. "
        "2-4 round cartoon wheels matching the machine color. "
        "Machine body shape must NOT change."
    ),
}


def rate_limited(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        with _rate_lock:
            now = time.time()
            _rate_log[:] = [t for t in _rate_log if now - t < 60]
            if len(_rate_log) >= RATE_LIMIT:
                return jsonify({"error": "Rate limit exceeded. Max 10/min."}), 429
            _rate_log.append(now)
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def prepare_image(src):
    if isinstance(src, (str, Path)):
        img = PIL.Image.open(src)
    else:
        img = PIL.Image.open(src)
    w, h = img.size
    mx = 1568
    if max(w, h) > mx:
        r = mx / max(w, h)
        img = img.resize((int(w * r), int(h * r)), PIL.Image.LANCZOS)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def do_generate(image, style, expression, body_style, face_placement):
    """Generate image(s) with optional body modifications."""
    client = get_client()
    gen_styles = STYLES if style == "all" else [style]
    body_extra = BODY_PROMPTS.get(body_style, "")
    results = {}

    for s in gen_styles:
        prompt = _short_prompt(s, expression, face_placement)
        if body_extra:
            prompt += " " + body_extra

        img_data, mime = generate_image(client, image, prompt, s, expression, face_placement)
        if img_data:
            b64 = base64.b64encode(img_data).decode("utf-8")
            results[f"{s}_{expression}"] = {"data": b64, "mime": mime or "image/png"}
        time.sleep(3)

    return results


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
@rate_limited
def upload():
    """Initial upload: analyze + generate."""
    if 'image' not in request.files:
        return jsonify({"error": "No image"}), 400

    file = request.files['image']
    if not file or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type"}), 400

    style = request.form.get('style', 'pixar')
    expression = request.form.get('expression', 'happy')
    personality = request.form.get('personality', '') or None
    body_style = request.form.get('body_style', 'face_only')
    gen_images = request.form.get('generate_images', 'true') == 'true'

    # Save upload persistently for regeneration
    session_id = session.get('session_id') or str(uuid.uuid4())[:12]
    session['session_id'] = session_id

    upload_dir = app.config['UPLOAD_FOLDER'] / session_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = file.filename.rsplit('.', 1)[1].lower()
    upload_path = upload_dir / f"original.{ext}"
    file.save(str(upload_path))
    session['upload_path'] = str(upload_path)
    session['original_filename'] = file.filename

    try:
        image = prepare_image(upload_path)

        # Phase 1: Analysis
        raw = call_gemini_analysis(get_client(), image, personality)
        data = parse_response(raw)
        if data is None:
            return jsonify({"error": "Failed to parse AI response"}), 500

        # Store analysis in session
        analysis_info = {
            "machine_type": data.get("machine_type", ""),
            "personality": data.get("personality", ""),
            "catchphrase": data.get("catchphrase_gr", ""),
            "face_placement": data.get("face_placement", {}),
            "animation_prompt": data.get("animation_prompt", ""),
            "prompts": data.get("prompts", {}),
        }
        session['analysis'] = analysis_info

        result = dict(analysis_info)
        result["status"] = "complete"
        result["session_id"] = session_id

        # Phase 2: Generate images
        if gen_images:
            gen_results = do_generate(image, style, expression, body_style,
                                      data.get("face_placement", {}))
            result["generated_images"] = gen_results

            # Save to disk
            job_id = str(uuid.uuid4())[:8]
            results_dir = app.config['RESULTS_FOLDER'] / session_id / job_id
            results_dir.mkdir(parents=True, exist_ok=True)

            for key, img_info in gen_results.items():
                img_bytes = base64.b64decode(img_info["data"])
                (results_dir / f"{key}.png").write_bytes(img_bytes)

            result["job_id"] = job_id
        else:
            result["generated_images"] = {}

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/regenerate', methods=['POST'])
@rate_limited
def regenerate():
    """Regenerate with same photo, different settings."""
    upload_path = session.get('upload_path')
    analysis = session.get('analysis')

    if not upload_path or not Path(upload_path).exists():
        return jsonify({"error": "No photo in session. Upload first."}), 400

    style = request.form.get('style', 'pixar')
    expression = request.form.get('expression', 'happy')
    body_style = request.form.get('body_style', 'face_only')

    try:
        image = prepare_image(upload_path)
        face = (analysis or {}).get("face_placement", {})

        gen_results = do_generate(image, style, expression, body_style, face)

        # Save
        session_id = session.get('session_id', 'unknown')
        job_id = str(uuid.uuid4())[:8]
        results_dir = app.config['RESULTS_FOLDER'] / session_id / job_id
        results_dir.mkdir(parents=True, exist_ok=True)

        for key, img_info in gen_results.items():
            img_bytes = base64.b64decode(img_info["data"])
            (results_dir / f"{key}.png").write_bytes(img_bytes)

        return jsonify({
            "status": "complete",
            "generated_images": gen_results,
            "job_id": job_id,
            "session_id": session_id,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/generate', methods=['POST'])
@rate_limited
def api_generate():
    """API endpoint for programmatic access."""
    if 'image' not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    file = request.files['image']
    if not file or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file. Accepted: jpg, jpeg, png, webp"}), 400

    style = request.form.get('style', 'pixar')
    expression = request.form.get('expression', 'neutral')
    personality = request.form.get('personality', None)
    body_style = request.form.get('body_style', 'face_only')
    gen_images = request.form.get('generate_images', 'true').lower() != 'false'

    try:
        image = prepare_image(file)
        client = get_client()

        raw = call_gemini_analysis(client, image, personality)
        data = parse_response(raw)
        if data is None:
            return jsonify({"error": "Failed to parse AI response"}), 500

        result = {
            "machine_type": data.get("machine_type", ""),
            "personality": data.get("personality", ""),
            "catchphrase": data.get("catchphrase_gr", ""),
            "face_placement": data.get("face_placement", {}),
            "prompts": data.get("prompts", {}),
            "animation_prompt": data.get("animation_prompt", ""),
        }

        if gen_images:
            result["generated_images"] = do_generate(
                image, style, expression, body_style, data.get("face_placement", {}))
        else:
            result["generated_images"] = {}

        result["status"] = "complete"
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/download-all')
def download_all_session():
    """Download ALL images from current session as ZIP."""
    session_id = session.get('session_id')
    if not session_id:
        return jsonify({"error": "No session"}), 404

    session_dir = app.config['RESULTS_FOLDER'] / session_id
    if not session_dir.exists():
        return jsonify({"error": "No results"}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(session_dir):
            for fname in files:
                fpath = Path(root) / fname
                arcname = fpath.relative_to(session_dir)
                zf.write(fpath, arcname)
    buf.seek(0)

    return send_file(buf, mimetype='application/zip',
                     as_attachment=True, download_name=f"talking_objects_{session_id}.zip")


@app.route('/download/<session_id>/<job_id>/<filename>')
def download_file(session_id, job_id, filename):
    results_dir = app.config['RESULTS_FOLDER'] / session_id / job_id
    return send_from_directory(str(results_dir), filename, as_attachment=True)


def cleanup_old_results(max_age_hours=24):
    for folder in [app.config['RESULTS_FOLDER'], app.config['UPLOAD_FOLDER']]:
        if not folder.exists():
            continue
        for item in folder.iterdir():
            if item.is_dir():
                age = time.time() - item.stat().st_mtime
                if age > max_age_hours * 3600:
                    shutil.rmtree(item, ignore_errors=True)


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
        import webbrowser, threading
        threading.Timer(1.5, lambda: webbrowser.open(f'http://localhost:{args.port}')).start()

    print(f"\n  Talking Objects Maker v2 — Web UI")
    print(f"  http://localhost:{args.port}")
    print(f"  http://0.0.0.0:{args.port} (network)\n")

    app.run(host='0.0.0.0', port=args.port, debug=False)
