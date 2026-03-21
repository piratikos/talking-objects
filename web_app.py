#!/usr/bin/env python3
"""
Talking Objects Maker v3 — Flask Web Interface with User Accounts
Upload photo → analyze → generate → regenerate. User accounts with SQLite.
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
                   send_from_directory, session, redirect, url_for, flash)
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
import PIL.Image

load_dotenv()

from talking_objects import (
    get_client, call_gemini_analysis, generate_image, _short_prompt,
    generate_text_only, generate_group_shot, TOOLGINI_TEAM,
    optimize_prompt_for_category, CLOTHING_OPTIONS,
    parse_response, load_presets, suggest_preset,
    STYLES, ALL_STYLES, EXPRESSIONS
)
from models import (
    create_user, authenticate_user, get_user_by_id,
    create_project, get_user_projects, get_project, delete_project,
    rename_project, delete_generation, add_generation
)

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET", "toolgini-talking-objects-2026")
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = Path(__file__).parent / 'uploads'
app.config['RESULTS_FOLDER'] = Path(__file__).parent / 'results'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

_rate_lock = Lock()
_rate_log = []
RATE_LIMIT = 10

# ── Config data (backgrounds, angles, body) ──────────────────

BACKGROUNDS = {
    "original": {},
    "toolgini_workshop": {
        "cartoon": "Colorful cartoon workshop background with wooden shelves full of tools, warm yellow lighting, wood shavings on the floor, TOOLGINI sign on the wall, cartoon style",
        "pixar": "Pixar-style 3D dark workshop with workbench, pegboard wall, warm desk lamp lighting, floating sawdust, TOOLGINI sign on brick wall, cinematic depth of field",
        "realistic": "Professional woodworking workshop, dark moody lighting, tools on pegboard wall, sawdust, desk lamp, shallow depth of field",
    },
    "modern_showroom": {
        "cartoon": "Clean white showroom with spotlights, cartoon style",
        "pixar": "Sleek modern showroom, soft gradient lighting, polished floor, reflections, 3D rendered",
        "realistic": "Product photography on white/grey background, studio softbox lighting, catalog style",
    },
    "trade_show": {
        "cartoon": "Cartoon trade show booth, colorful banners, exhibition hall",
        "pixar": "3D trade show booth, professional banners, bright hall lighting, TOOLGINI branding",
        "realistic": "Woodworking trade show floor, booth setup, exhibition lighting, blurred visitors",
    },
    "carpenters_dream": {
        "cartoon": "Cozy cartoon carpenter workshop, fireplace glow, vintage tools",
        "pixar": "Pixar old carpenter workshop, golden light through dusty windows, wooden beams, vintage tools, warm palette",
        "realistic": "Traditional workshop, golden hour sunlight, dust in light beams, worn workbench, warm nostalgic photography",
    },
    "outdoor": {
        "cartoon": "Cartoon outdoor scene, green grass, blue sky, trees",
        "pixar": "Pixar outdoor meadow, golden hour, dramatic clouds, cinematic wide shot",
        "realistic": "Outdoor natural light, green landscape, professional product photography",
    },
    "studio": {
        "cartoon": "Solid dark background, dramatic spotlights, clean studio",
        "pixar": "Dark grey background, dramatic rim lighting, volumetric light, 3D studio render",
        "realistic": "Dark grey background, rim lighting, professional studio product photography",
    },
}

CAMERA_ANGLES = {
    "original": {},
    "front_facing": {
        "cartoon": "Front-facing view, character looks at viewer, cartoon composition",
        "pixar": "Cinematic front-facing hero shot, confident expression, shallow depth of field, movie poster",
        "realistic": "Straight-on frontal product photograph, centered, professional",
    },
    "three_quarter": {
        "cartoon": "3/4 angle showing depth, cartoon perspective",
        "pixar": "Cinematic 3/4 angle, dramatic lighting, movie still composition",
        "realistic": "Professional 3/4 angle product photography, studio lighting",
    },
    "low_angle": {
        "cartoon": "Low angle looking up, big and powerful, hero pose",
        "pixar": "Dramatic low-angle, heroic pose, rim lighting from behind, movie poster style",
        "realistic": "Low angle product photography, imposing and powerful",
    },
    "eye_level": {
        "cartoon": "Eye level, face to face, friendly angle",
        "pixar": "Eye-level medium shot, intimate close-up, bokeh background",
        "realistic": "Eye level product photograph, face to face",
    },
    "isometric": {
        "cartoon": "Isometric top-down 3/4 angle, clean illustration",
        "pixar": "Isometric 3/4 top-down, clean 3D visualization, even lighting",
        "realistic": "Isometric product shot, clean catalog photography",
    },
}

BODY_PROMPTS = {
    "face_only": "",
    "face_arms": (
        "Also add small robot-style arms from the sides with 3-fingered hands. "
        "Metallic, Wall-E style. Machine body must NOT change."
    ),
    "face_arms_legs": (
        "Also add robot arms from sides with 3-fingered hands and short sturdy legs at bottom. "
        "Metallic, industrial, Wall-E style. Machine body must NOT change."
    ),
    "face_wheels": (
        "Also add cartoon wheels at the bottom. 2-4 round wheels matching machine color. "
        "Machine body must NOT change."
    ),
}


# ── Auth ──────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, user_dict):
        self.id = user_dict["id"]
        self.email = user_dict["email"]
        self.name = user_dict["name"]


@login_manager.user_loader
def load_user(user_id):
    u = get_user_by_id(int(user_id))
    return User(u) if u else None


# ── Helpers ───────────────────────────────────────────────────

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


def allowed_file(fn):
    return '.' in fn and fn.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def prepare_image(src):
    img = PIL.Image.open(src if isinstance(src, (str, Path)) else src)
    w, h = img.size
    if max(w, h) > 1568:
        r = 1568 / max(w, h)
        img = img.resize((int(w * r), int(h * r)), PIL.Image.LANCZOS)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def get_bg_prompt(bg, style, custom=""):
    if bg == "custom" and custom:
        return f"BACKGROUND CHANGE: Replace background with: {custom}"
    if bg == "original" or bg not in BACKGROUNDS:
        return ""
    txt = BACKGROUNDS[bg].get(style, BACKGROUNDS[bg].get("pixar", ""))
    return f"BACKGROUND CHANGE: Replace background with: {txt}"


def get_angle_prompt(angle, style):
    if angle == "original" or angle not in CAMERA_ANGLES:
        return ""
    txt = CAMERA_ANGLES[angle].get(style, CAMERA_ANGLES[angle].get("pixar", ""))
    return f"Camera angle: {txt}"


def do_generate(image, style, expression, body_style, face_placement,
                background="original", camera_angle="original", custom_bg="",
                category="MACHINE/TOOL", clothing="none"):
    client = get_client()
    gen_styles = STYLES if style == "all" else [style]
    results = {}

    print(f"[DEBUG] do_generate: style={style} expr={expression} body={body_style} bg={background} angle={camera_angle} cat={category} cloth={clothing}")

    for s in gen_styles:
        prompt = _short_prompt(s, expression, face_placement)
        prompt = optimize_prompt_for_category(prompt, category, body_style, clothing)
        bg = get_bg_prompt(background, s, custom_bg)
        if bg:
            prompt += " " + bg
        ang = get_angle_prompt(camera_angle, s)
        if ang:
            prompt += " " + ang

        print(f"[DEBUG] Style={s}: cat={category} cloth={clothing} bg={'YES' if bg else 'no'} angle={'YES' if ang else 'no'}")
        img_data, mime = generate_image(client, image, prompt, s, expression, face_placement)
        if img_data:
            b64 = base64.b64encode(img_data).decode("utf-8")
            results[f"{s}_{expression}"] = {
                "data": b64, "mime": mime or "image/png", "prompt": prompt
            }
        time.sleep(3)

    return results


def get_user_dir():
    if current_user.is_authenticated:
        return str(current_user.id)
    return session.get('session_id') or str(uuid.uuid4())[:12]


# ── Auth routes ───────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('app_page'))

    if request.method == 'POST':
        email = request.form.get('email', '')
        password = request.form.get('password', '')
        user = authenticate_user(email, password)
        if user:
            login_user(User(user), remember=True)
            return redirect(url_for('app_page'))
        return render_template('login.html', error="Wrong email or password")

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        name = request.form.get('name', '').strip()

        if not email or not password or not name:
            return render_template('register.html', error="All fields required")
        if len(password) < 4:
            return render_template('register.html', error="Password too short (min 4)")

        user = create_user(email, password, name)
        if user is None:
            return render_template('register.html', error="Email already registered")

        login_user(User(user), remember=True)
        return redirect(url_for('app_page'))

    return render_template('register.html')


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


# ── Main routes ───────────────────────────────────────────────

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('app_page'))
    return redirect(url_for('login'))


@app.route('/app')
def app_page():
    is_guest = not current_user.is_authenticated
    user_name = current_user.name if not is_guest else "Guest"
    return render_template('index.html', user_name=user_name, is_guest=is_guest)


@app.route('/guest')
def guest():
    session['session_id'] = str(uuid.uuid4())[:12]
    return redirect(url_for('app_page'))


@app.route('/projects')
@login_required
def projects_page():
    projects = get_user_projects(current_user.id)
    return render_template('projects.html', projects=projects, user_name=current_user.name)


@app.route('/projects/<int:pid>')
@login_required
def project_detail(pid):
    project, generations = get_project(pid, current_user.id)
    if not project:
        return redirect(url_for('projects_page'))

    # Check which generation images exist on disk
    for g in generations:
        g['exists'] = Path(g.get('image_path', '')).exists() if g.get('image_path') else False
        if g['exists']:
            # Make path relative for serving
            g['serve_path'] = f"/project-image/{pid}/{g['id']}"
    return render_template('project_detail.html', project=project, generations=generations, user_name=current_user.name)


@app.route('/project-image/<int:pid>/<int:gid>')
@login_required
def serve_project_image(pid, gid):
    """Serve a generated image from a project."""
    project, generations = get_project(pid, current_user.id)
    if not project:
        return "Not found", 404
    for g in generations:
        if g['id'] == gid and g.get('image_path'):
            p = Path(g['image_path'])
            if p.exists():
                return send_file(str(p))
    return "Not found", 404


@app.route('/projects/<int:pid>/rename', methods=['POST'])
@login_required
def rename_project_route(pid):
    name = request.form.get('name', '').strip()
    if name:
        rename_project(pid, current_user.id, name)
    if request.headers.get('Accept') == 'application/json':
        return jsonify({"ok": True})
    return redirect(url_for('project_detail', pid=pid))


@app.route('/projects/<int:pid>/delete', methods=['POST'])
@login_required
def delete_project_route(pid):
    delete_project(pid, current_user.id)
    proj_dir = app.config['RESULTS_FOLDER'] / str(current_user.id) / str(pid)
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)
    return redirect(url_for('projects_page'))


@app.route('/generations/<int:gid>/delete', methods=['POST'])
@login_required
def delete_generation_route(gid):
    delete_generation(gid, current_user.id)
    pid = request.form.get('project_id')
    if pid:
        return redirect(url_for('project_detail', pid=int(pid)))
    return redirect(url_for('projects_page'))


@app.route('/projects/<int:pid>/download')
@login_required
def download_project(pid):
    """Download all images from a project as ZIP."""
    project, generations = get_project(pid, current_user.id)
    if not project:
        return "Not found", 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for g in generations:
            p = Path(g.get('image_path', ''))
            if p.exists():
                zf.write(p, f"{g['style']}_{g['expression']}.png")
    buf.seek(0)
    name = (project.get('machine_type') or 'project').replace(' ', '_')
    return send_file(buf, mimetype='application/zip', as_attachment=True,
                     download_name=f"{name}_{pid}.zip")


# ── Upload / Generate / Regenerate ────────────────────────────

@app.route('/upload', methods=['POST'])
@rate_limited
def upload():
    if 'image' not in request.files:
        return jsonify({"error": "No image"}), 400

    file = request.files['image']
    if not file or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type"}), 400

    style = request.form.get('style', 'pixar')
    expression = request.form.get('expression', 'happy')
    personality = request.form.get('personality', '') or None
    body_style = request.form.get('body_style', 'face_only')
    background = request.form.get('background', 'original')
    camera_angle = request.form.get('camera_angle', 'original')
    custom_bg = request.form.get('custom_bg', '')
    clothing = request.form.get('clothing', 'none')
    gen_images = request.form.get('generate_images', 'true') == 'true'

    user_dir = get_user_dir()
    session['session_id'] = user_dir

    upload_dir = app.config['UPLOAD_FOLDER'] / user_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = file.filename.rsplit('.', 1)[1].lower()
    upload_path = upload_dir / f"original.{ext}"
    file.save(str(upload_path))
    session['upload_path'] = str(upload_path)

    try:
        image = prepare_image(upload_path)

        raw = call_gemini_analysis(get_client(), image, personality)
        data = parse_response(raw)
        if data is None:
            return jsonify({"error": "Failed to parse AI response"}), 500

        analysis_info = {
            "machine_type": data.get("machine_type", ""),
            "personality": data.get("personality", ""),
            "catchphrase": data.get("catchphrase_gr", ""),
            "face_placement": data.get("face_placement", {}),
            "animation_prompt": data.get("animation_prompt", ""),
            "prompts": data.get("prompts", {}),
        }
        session['analysis'] = analysis_info

        # Save project to DB for logged-in users
        project_id = None
        if current_user.is_authenticated:
            project_id = create_project(
                current_user.id, file.filename, str(upload_path),
                analysis_info["machine_type"], analysis_info["personality"],
                analysis_info["catchphrase"]
            )
            session['project_id'] = project_id

        result = dict(analysis_info)
        result["status"] = "complete"

        if gen_images:
            detected_cat = data.get("category", "MACHINE/TOOL")
            gen_results = do_generate(image, style, expression, body_style,
                                      data.get("face_placement", {}),
                                      background, camera_angle, custom_bg,
                                      detected_cat, clothing)
            result["generated_images"] = gen_results

            # Save files
            results_dir = app.config['RESULTS_FOLDER'] / user_dir / (str(project_id) if project_id else str(uuid.uuid4())[:8])
            results_dir.mkdir(parents=True, exist_ok=True)

            for key, img_info in gen_results.items():
                img_bytes = base64.b64decode(img_info["data"])
                img_path = results_dir / f"{key}.png"
                img_path.write_bytes(img_bytes)

                if project_id:
                    s, e = key.rsplit("_", 1)
                    add_generation(project_id, s, e, body_style, background,
                                   camera_angle, str(img_path), img_info.get("prompt", ""))
        else:
            result["generated_images"] = {}

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/regenerate', methods=['POST'])
@rate_limited
def regenerate():
    mode = request.form.get('mode', 'photo')
    style = request.form.get('style', 'pixar')
    expression = request.form.get('expression', 'happy')
    body_style = request.form.get('body_style', 'face_only')
    background = request.form.get('background', 'original')
    camera_angle = request.form.get('camera_angle', 'original')
    custom_bg = request.form.get('custom_bg', '')
    clothing = request.form.get('clothing', 'none')

    print(f"[DEBUG] /regenerate mode={mode}")

    try:
        if mode == 'text':
            # Text-only regeneration — no photo
            description = session.get('last_description', '')
            machine_type = session.get('last_machine_type', 'object')
            if not description:
                return jsonify({"error": "No description in session. Use 'From Description' tab first."}), 400

            client = get_client()
            category = session.get('last_category', 'MACHINE/TOOL')
            img_data, mime = generate_text_only(
                client, description, machine_type, style, expression,
                body_style, background, camera_angle, category, clothing
            )
            gen_results = {}
            if img_data:
                b64 = base64.b64encode(img_data).decode("utf-8")
                gen_results[f"{style}_{expression}"] = {
                    "data": b64, "mime": mime or "image/png", "mode": "text"
                }

        else:
            # Photo-based regeneration
            upload_path = session.get('upload_path')
            analysis = session.get('analysis')
            if not upload_path or not Path(upload_path).exists():
                return jsonify({"error": "No photo in session. Upload first."}), 400

            image = prepare_image(upload_path)
            face = (analysis or {}).get("face_placement", {})
            detected_cat = (analysis or {}).get("category", "MACHINE/TOOL")

            gen_results = do_generate(image, style, expression, body_style, face,
                                      background, camera_angle, custom_bg, detected_cat, clothing)

        user_dir = get_user_dir()
        project_id = session.get('project_id')
        results_dir = app.config['RESULTS_FOLDER'] / user_dir / (str(project_id) if project_id else str(uuid.uuid4())[:8])
        results_dir.mkdir(parents=True, exist_ok=True)

        for key, img_info in gen_results.items():
            img_bytes = base64.b64decode(img_info["data"])
            img_path = results_dir / f"{key}.png"
            img_path.write_bytes(img_bytes)

            if project_id and current_user.is_authenticated:
                s, e = key.rsplit("_", 1)
                add_generation(project_id, s, e, body_style, background,
                               camera_angle, str(img_path), img_info.get("prompt", ""))

        return jsonify({"status": "complete", "generated_images": gen_results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/generate', methods=['POST'])
@rate_limited
def api_generate():
    if 'image' not in request.files:
        return jsonify({"error": "No image file"}), 400
    file = request.files['image']
    if not file or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file"}), 400

    style = request.form.get('style', 'pixar')
    expression = request.form.get('expression', 'neutral')
    personality = request.form.get('personality', None)
    body_style = request.form.get('body_style', 'face_only')
    background = request.form.get('background', 'original')
    camera_angle = request.form.get('camera_angle', 'original')
    custom_bg = request.form.get('custom_bg', '')
    gen_images = request.form.get('generate_images', 'true').lower() != 'false'

    try:
        image = prepare_image(file)
        raw = call_gemini_analysis(get_client(), image, personality)
        data = parse_response(raw)
        if not data:
            return jsonify({"error": "Parse failed"}), 500

        result = {
            "machine_type": data.get("machine_type", ""),
            "personality": data.get("personality", ""),
            "face_placement": data.get("face_placement", {}),
            "prompts": data.get("prompts", {}),
            "status": "complete",
        }
        if gen_images:
            result["generated_images"] = do_generate(
                image, style, expression, body_style, data.get("face_placement", {}),
                background, camera_angle, custom_bg)
        else:
            result["generated_images"] = {}
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/generate-text', methods=['POST'])
@rate_limited
def generate_text():
    """Generate from text description only (no photo)."""
    description = request.form.get('description', '')
    machine_type = request.form.get('machine_type', 'woodworking machine')
    style = request.form.get('style', 'pixar')
    expression = request.form.get('expression', 'happy')
    body_style = request.form.get('body_style', 'face_only')
    background = request.form.get('background', 'original')
    camera_angle = request.form.get('camera_angle', 'original')
    clothing = request.form.get('clothing', 'none')
    category = request.form.get('category', 'MACHINE/TOOL')

    if not description:
        return jsonify({"error": "Please describe your object"}), 400

    # Save for regeneration
    session['last_description'] = description
    session['last_machine_type'] = machine_type
    session['last_category'] = category

    print(f"[DEBUG] /generate-text: {machine_type} / {style} / {expression} / body={body_style}")

    try:
        client = get_client()
        img_data, mime = generate_text_only(
            client, description, machine_type, style, expression,
            body_style, background, camera_angle, category, clothing
        )

        result = {"status": "complete", "generated_images": {}, "machine_type": machine_type}
        if img_data:
            b64 = base64.b64encode(img_data).decode("utf-8")
            result["generated_images"][f"{style}_{expression}"] = {
                "data": b64, "mime": mime or "image/png"
            }
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/generate-group', methods=['POST'])
@rate_limited
def generate_group():
    """Generate group shot of multiple machines."""
    print(f"[DEBUG] /generate-group called")
    data = request.get_json() or {}
    print(f"[DEBUG] Group data: {len(data.get('machines',[]))} machines")
    machines = data.get('machines', [])
    use_preset = data.get('use_preset', False)
    background = data.get('background', 'toolgini_workshop')
    camera_angle = data.get('camera_angle', 'front_facing')

    if use_preset:
        machines = TOOLGINI_TEAM

    if not machines or len(machines) < 2:
        return jsonify({"error": "Need at least 2 machines"}), 400

    print(f"[DEBUG] Group shot: {len(machines)} machines, bg={background}")

    try:
        client = get_client()
        img_data, mime = generate_group_shot(client, machines, background, camera_angle)

        result = {"status": "complete", "generated_images": {}}
        if img_data:
            b64 = base64.b64encode(img_data).decode("utf-8")
            result["generated_images"]["group_shot"] = {
                "data": b64, "mime": mime or "image/png"
            }
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/edit-image', methods=['POST'])
@rate_limited
def edit_image():
    """Edit a generated image with text instruction."""
    image_data = request.form.get('image_data', '')
    edit_instruction = request.form.get('edit_instruction', '')

    if not image_data or not edit_instruction:
        return jsonify({"error": "Image data and edit instruction required"}), 400

    print(f"[DEBUG] /edit-image: {edit_instruction[:100]}")

    try:
        from google.genai import types
        img_bytes = base64.b64decode(image_data)
        img = PIL.Image.open(io.BytesIO(img_bytes))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        client = get_client()
        prompt = f"Edit this image: {edit_instruction}. Keep everything else exactly the same."

        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[prompt, img],
            config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])
        )

        if (response.candidates and response.candidates[0].content
                and response.candidates[0].content.parts):
            for part in response.candidates[0].content.parts:
                if part.inline_data is not None:
                    b64 = base64.b64encode(part.inline_data.data).decode("utf-8")
                    return jsonify({
                        "status": "complete",
                        "generated_images": {
                            "edited": {"data": b64, "mime": part.inline_data.mime_type or "image/png"}
                        }
                    })

        return jsonify({"error": "No image returned from edit"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/download-all')
def download_all_session():
    user_dir = get_user_dir()
    session_dir = app.config['RESULTS_FOLDER'] / user_dir
    if not session_dir.exists():
        return jsonify({"error": "No results"}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(session_dir):
            for fn in files:
                fp = Path(root) / fn
                zf.write(fp, fp.relative_to(session_dir))
    buf.seek(0)
    return send_file(buf, mimetype='application/zip', as_attachment=True,
                     download_name=f"talking_objects_{user_dir}.zip")


def cleanup_old_results(max_age_hours=72):
    for folder in [app.config['UPLOAD_FOLDER']]:
        if not folder.exists():
            continue
        for item in folder.iterdir():
            if item.is_dir() and (time.time() - item.stat().st_mtime) > max_age_hours * 3600:
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

    print(f"\n  Talking Objects Maker v3 — Web UI + Accounts")
    print(f"  http://localhost:{args.port}")
    print(f"  http://0.0.0.0:{args.port} (network)\n")

    app.run(host='0.0.0.0', port=args.port, debug=False)
