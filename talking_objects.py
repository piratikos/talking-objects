#!/usr/bin/env python3
"""
Talking Objects Maker v2 — Gemini 2.5 Pro Vision + Image Generation
1. Analyzes machine photo with Gemini 2.5 Pro (vision)
2. Generates 12 text prompts (3 styles x 4 expressions)
3. Generates actual images with Gemini 2.5 Flash (image generation)
4. Saves everything to output folder
"""

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import PIL.Image

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PRESETS_PATH = SCRIPT_DIR / "presets.json"
MAX_IMAGE_EDGE = 1568

STYLES = ["cartoon", "pixar", "realistic"]
ALL_STYLES = ["cartoon", "pixar", "realistic", "plushcore", "action_figure",
              "anime", "low_poly", "claymation", "chibi", "blueprint", "cyberpunk"]
EXPRESSIONS = ["neutral", "happy", "serious", "surprised"]

SYSTEM_PROMPT = """You are an expert industrial product photographer and Pixar character designer specialized in creating "talking object" characters from real product photos.

When you receive a photo of a machine or object, follow these steps EXACTLY:

## STEP 1 — MACHINE ANATOMY (be exhaustive)
Describe EVERY visible component:
- Overall shape, proportions, orientation (landscape/portrait/cubic)
- Main body: exact color, material (metal/plastic/rubber), finish (matte/glossy/brushed/textured)
- Each distinct component: what it is, color, material, exact position
- Surface details: ventilation holes/grilles, textures, seams
- Controls: buttons, dials, displays, switches, indicators
- Accessories: handles, hoses, cables, work tables, extensions
- Logos, text, brand markings (describe position and style)
- Any features that ALREADY resemble face parts

## STEP 2 — ENVIRONMENT (exact reproduction)
- Surface the machine sits on, background, lighting direction/temperature
- Atmospheric effects, mood, camera angle and distance

## STEP 3 — FACE DESIGN
IMPORTANT PLACEMENT RULES:
- Face (eyes + mouth) should be on the UPPER portion of the machine body
- Eyes on the top/head area of the machine
- Mouth just below the eyes but still on the upper body
- The brand logo and any text labels must remain completely visible and unobstructed
- Place facial features ABOVE or AWAY from any logos
- NEVER place face features on control panels, displays, or ventilation areas

EYES: Look for the upper part of the machine body. Prefer existing features (LEDs, displays, sensors) as eye locations. Describe EXACT position. Iris color matching machine accent color.
MOUTH: Below the eyes on the upper body area. Must NOT cover logos, controls, or labels. Describe EXACT position relative to other features.
EYEBROWS: Thick, expressive eyebrows ABOVE the eyes — essential for showing emotion.
PERSONALITY: Auto-detect from shape language (round=friendly, angular=powerful, complex=clever).

## STEP 4 — GENERATE PROMPTS (3 styles x 4 expressions = 12 total)

### STYLE A: CARTOON — Bold, friendly. Thomas the Tank Engine style.
Features: large eyes with thick outlines, thick expressive eyebrows, wide mouth with simple curves, bold colors.

### STYLE B: PIXAR — High-quality 3D, cinematic. Cars/Wall-E style.
Features: detailed realistic eyes with eyelids and catchlights, thick 3D eyebrows, mouth with pink lips and visible teeth when smiling, subsurface scattering on face features, ambient occlusion, soft rim lighting, professional 3D character design. Face features have slight 3D relief — integrated into surface, not flat stickers.

### STYLE C: REALISTIC — Subtle, integrated into machine design.
Features: eyes look like indicator lights, mouth looks like a panel seam, features don't break industrial aesthetic.

### EXPRESSIONS (with eyebrow guidance):
- NEUTRAL: Calm confident. Relaxed eyebrows, slight smile.
- HAPPY: Big smile showing teeth, bright eyes, RAISED eyebrows.
- SERIOUS: Focused eyes, firm mouth, ANGLED DOWN eyebrows.
- SURPRISED: Wide round eyes, open O mouth, HIGH RAISED eyebrows.

Each prompt MUST include: complete machine description, exact face placement (with logo protection note), full environment, style-specific quality notes.

## STEP 5 — ANIMATION PROMPT
"Animate this character speaking to camera. Lip sync, blinks every 3-4s, subtle body sway. Camera static."

## OUTPUT — Return ONLY this JSON (no markdown backticks):
{
  "machine_type": "string",
  "personality": "string",
  "catchphrase_gr": "Greek string",
  "face_placement": {
    "eyes": "exact description",
    "eyes_color": "color",
    "mouth": "exact description",
    "mouth_size": "size"
  },
  "prompts": {
    "cartoon": {"neutral": "...", "happy": "...", "serious": "...", "surprised": "..."},
    "pixar": {"neutral": "...", "happy": "...", "serious": "...", "surprised": "..."},
    "realistic": {"neutral": "...", "happy": "...", "serious": "...", "surprised": "..."}
  },
  "animation_prompt": "Animate this character speaking..."
}"""


def load_presets():
    if PRESETS_PATH.exists():
        return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    return {}


def suggest_preset(machine_type, presets):
    for keyword, data in presets.items():
        if keyword.lower() in machine_type.lower():
            return data
    return None


def prepare_image(image_path):
    """Load and resize image if needed."""
    path = Path(image_path)
    if not path.exists():
        print(f"Error: {path} not found")
        sys.exit(1)

    img = PIL.Image.open(path)
    w, h = img.size

    if max(w, h) > MAX_IMAGE_EDGE:
        ratio = MAX_IMAGE_EDGE / max(w, h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), PIL.Image.LANCZOS)
        print(f"  Resized: {w}x{h} -> {new_w}x{new_h}")

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    return img


def get_client():
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set")
        print("Get one from https://aistudio.google.com/apikey")
        print("Add to ~/Projects/talking-objects/.env")
        sys.exit(1)
    return genai.Client(api_key=api_key)


def call_gemini_analysis(client, image, personality_override=None):
    """Step 1: Analyze image with Gemini 2.5 Pro Vision."""
    from google.genai import types

    user_msg = "Analyze this machine/object photo and generate talking character prompts. Return ONLY valid JSON, no markdown backticks."
    if personality_override:
        user_msg += f'\n\nUse this personality: "{personality_override}"'

    last_error = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=[image, user_msg],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.7,
                    max_output_tokens=8000,
                )
            )
            return response.text
        except Exception as e:
            last_error = e
            err_str = str(e).lower()

            # Content filter — retry with softened prompt
            if "blocked" in err_str or "safety" in err_str or "filter" in err_str:
                print(f"  Content filter triggered, retrying with softened prompt...")
                user_msg = "Describe this industrial equipment photo in detail and suggest where cartoon face features could be added. Return JSON."
                time.sleep(2)
                continue

            # Rate limit — exponential backoff
            if "429" in err_str or "rate" in err_str or "quota" in err_str:
                wait = (2 ** attempt) * 3
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            # Network error — simple retry
            if attempt < 2:
                wait = (attempt + 1) * 2
                print(f"  Retry in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"Error: API failed after 3 attempts: {last_error}")
                sys.exit(1)

    print(f"Error: API failed after 3 attempts: {last_error}")
    sys.exit(1)


def _short_prompt(style, expression, face_placement=None):
    """Generate short, precise prompts for Gemini Flash Image generation."""
    face = face_placement or {}
    eyes_pos = face.get("eyes", "on the upper portion of the machine body")
    mouth_pos = face.get("mouth", "on the front panel below the eyes")
    eyes_color = face.get("eyes_color", "matching the machine accent color")

    expr_desc = {
        "neutral": "calm confident expression, slight smile",
        "happy": "big warm smile showing teeth, bright cheerful eyes, raised eyebrows",
        "serious": "determined focused expression, firm mouth, angled eyebrows",
        "surprised": "wide round eyes, open O-shaped mouth, raised eyebrows",
    }.get(expression, "neutral expression")

    placement_rules = (
        f"Place eyes {eyes_pos}. Place mouth {mouth_pos}. "
        "CRITICAL RULES: "
        "1) Do NOT cover or alter any logos, brand text, or labels — they must remain fully visible. "
        "2) Face features must be ON the machine surface, not floating outside. "
        "3) Do NOT change machine shape, add limbs, or modify mechanical parts. "
        "4) Features should look PART of the machine, integrated into the surface with slight 3D relief. "
        "5) Keep the EXACT same background, lighting, and environment. "
        "6) Add thick expressive eyebrows above the eyes showing emotion."
    )

    if style == "cartoon":
        return (
            f"Edit this photo: add a cartoon face directly on the machine's upper body surface. "
            f"Add two big round cartoon eyes with {eyes_color} irises, white sclera, black pupils, and thick outlines. "
            f"Add thick expressive cartoon eyebrows above the eyes. "
            f"Add a wide friendly mouth with simple curved lips. "
            f"{expr_desc}. "
            f"{placement_rules} "
            "Style: high-quality cartoon decal painted onto the machine surface, bold outlines."
        )

    elif style == "pixar":
        return (
            f"Edit this photo: add a Pixar-style 3D animated face on the machine's upper body surface. "
            f"Add two expressive 3D eyes with {eyes_color} irises, detailed pupils, subtle eyelids, small light reflections. "
            f"Add thick 3D eyebrows above the eyes showing emotion. "
            f"Add a 3D mouth with soft pink lips and visible white teeth. "
            f"{expr_desc}. "
            f"{placement_rules} "
            "Style: Pixar animation quality, subsurface scattering on face features, ambient occlusion, soft rim lighting, professional 3D character design."
        )

    elif style == "realistic":
        return (
            f"Edit this photo: subtly add face-like features to the machine's front surface. "
            f"Add two glowing eye-like indicators with {eyes_color} glow at the eye positions. "
            f"Add a subtle mouth-like crease or shadow line. "
            f"{expr_desc}. "
            f"{placement_rules} "
            "Style: photorealistic, features look like real machine parts — indicator lights for eyes, panel seam for mouth."
        )

    elif style == "plushcore":
        return (
            f"Edit this photo: transform this machine into a soft plush toy version. "
            f"Squishy fabric texture, rounded edges, felt material. Button eyes with {eyes_color} felt circles, stitched smile mouth. "
            f"{expr_desc}. "
            f"{placement_rules} "
            "Style: stuffed toy aesthetic, warm soft lighting, shallow depth of field, collectible plush product photo."
        )

    elif style == "action_figure":
        return (
            f"Show this machine as a collectible action figure toy inside clear plastic blister packaging. "
            f"Cardboard backing says TOOLGINI at top. Machine has cartoon face with {eyes_color} eyes, articulated joints, small accessories. "
            f"{expr_desc}. "
            "Style: professional toy product photography on white background, blister pack packaging."
        )

    elif style == "anime":
        return (
            f"Edit this photo: render in anime/manga style. "
            f"Machine has large sparkly anime eyes with {eyes_color} irises and dramatic highlights, small cute mouth. "
            f"{expr_desc}. "
            f"{placement_rules} "
            "Style: Japanese animation, cel-shaded, speed lines in background, vibrant colors."
        )

    elif style == "low_poly":
        return (
            f"Edit this photo: render as a low-poly 3D model character. "
            f"Geometric faceted eyes with {eyes_color}, angular mouth shape. "
            f"{expr_desc}. "
            f"{placement_rules} "
            "Style: low-poly 3D, flat shading, limited color palette, indie game character aesthetic."
        )

    elif style == "claymation":
        return (
            f"Edit this photo: render as a claymation stop-motion character. "
            f"Clay eyes with {eyes_color} painted pupils, slightly rough clay mouth. "
            f"{expr_desc}. "
            f"{placement_rules} "
            "Style: Wallace & Gromit aesthetic, visible fingerprints in clay, slightly imperfect, warm handmade feel."
        )

    elif style == "chibi":
        return (
            f"Edit this photo: render as a chibi character with oversized head (60% of body). "
            f"Huge adorable eyes with {eyes_color} irises, tiny mouth, very cute compact proportions. "
            f"{expr_desc}. "
            f"{placement_rules} "
            "Style: kawaii Japanese chibi, super cute, simplified features, pastel accents."
        )

    elif style == "blueprint":
        return (
            f"Render as a technical blueprint drawing showing this machine as a character. "
            f"White line art eyes and mouth on blue background, engineering annotations. "
            f"{expr_desc}. "
            "Style: blue background, white lines, grid paper texture, technical illustration, engineering drawing."
        )

    elif style == "cyberpunk":
        return (
            f"Edit this photo: render in cyberpunk neon style. "
            f"Machine has glowing neon {eyes_color} eyes, neon mouth outline, holographic UI elements. "
            f"{expr_desc}. "
            f"{placement_rules} "
            "Style: dark background, neon orange and blue glow, rain reflections, futuristic workshop, cyberpunk aesthetic."
        )

    else:
        return (
            f"Edit this photo: add a friendly face to the machine. "
            f"Add eyes with {eyes_color} color and a mouth. {expr_desc}. "
            f"{placement_rules}"
        )


def generate_image(client, original_image, prompt, style, expression, face_placement=None):
    """Step 2: Generate image with Gemini 2.5 Flash Image (nano-banana)."""
    from google.genai import types

    # Use the prompt passed by caller (includes body/background/angle)
    # Only fallback to _short_prompt if caller passes empty prompt
    gen_prompt = prompt if prompt else _short_prompt(style, expression, face_placement)
    print(f"[DEBUG] Prompt sent to Gemini ({len(gen_prompt)} chars): {gen_prompt[:300]}...")

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=[gen_prompt, original_image],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                )
            )

            # Extract image from response
            if (response.candidates
                    and response.candidates[0].content
                    and response.candidates[0].content.parts):
                for part in response.candidates[0].content.parts:
                    if part.inline_data is not None:
                        return part.inline_data.data, part.inline_data.mime_type

            # No image in response — might be filtered or empty
            if attempt < 2:
                print("empty response, retrying...", end=" ", flush=True)
                time.sleep(3)
                continue
            return None, None

        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "rate" in err_str:
                wait = (2 ** attempt) * 5
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if "blocked" in err_str or "safety" in err_str:
                print(f"    Content filter blocked {style}_{expression}, skipping")
                return None, None
            if attempt < 2:
                time.sleep(3)
                continue
            print(f"    Image gen failed for {style}_{expression}: {e}")
            return None, None

    return None, None


def generate_text_only(client, description, machine_type, style, expression, body_style="face_only", background="original", camera_angle="original"):
    """Generate image from text description only (no reference photo)."""
    from google.genai import types

    expr_desc = {
        "neutral": "calm confident expression",
        "happy": "big happy smile, bright cheerful eyes",
        "serious": "determined focused look",
        "surprised": "wide surprised eyes, open mouth",
    }.get(expression, "neutral expression")

    style_desc = {
        "cartoon": "cartoon illustration style with bold outlines, bright colors",
        "pixar": "Pixar-quality 3D render, cinematic lighting, subsurface scattering",
        "realistic": "photorealistic render, studio product photography",
        "plushcore": "soft plush toy version, squishy fabric, button eyes, stitched smile",
        "action_figure": "collectible action figure in clear blister packaging, TOOLGINI on cardboard backing",
        "anime": "anime/manga style, large sparkly eyes, cel-shaded, speed lines",
        "low_poly": "low-poly 3D model, flat shading, geometric, indie game style",
        "claymation": "claymation stop-motion, visible fingerprints in clay, Wallace & Gromit style",
        "chibi": "chibi character, oversized head 60% of body, huge adorable eyes, kawaii",
        "blueprint": "technical blueprint drawing, blue background, white lines, engineering annotations",
        "cyberpunk": "cyberpunk neon style, glowing neon lights, dark background, holographic UI",
    }.get(style, "3D rendered")

    body_desc = {
        "face_only": "",
        "face_arms": "Small mechanical robot arms on the sides with 3-fingered hands. ",
        "face_arms_legs": "Mechanical robot arms on sides and short sturdy legs at bottom. Wall-E style. ",
        "face_wheels": "Cartoon wheels at the bottom so it can drive around. ",
    }.get(body_style, "")

    prompt = (
        f"{style_desc} 3D render of a {machine_type} woodworking machine character. "
        f"The machine has {description}. "
        f"Anthropomorphic face: expressive eyes with eyebrows, a mouth with {expr_desc}. "
        f"{body_desc}"
        f"Toolgini branding. Ultra-detailed, professional render."
    )

    print(f"[DEBUG] Text-only prompt ({len(prompt)} chars): {prompt[:300]}...")

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=[prompt],
                config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])
            )
            if (response.candidates and response.candidates[0].content
                    and response.candidates[0].content.parts):
                for part in response.candidates[0].content.parts:
                    if part.inline_data is not None:
                        return part.inline_data.data, part.inline_data.mime_type
            if attempt < 2:
                time.sleep(3)
                continue
            return None, None
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
                continue
            return None, None

    return None, None


def generate_group_shot(client, machines, background="toolgini_workshop", camera_angle="front_facing"):
    """Generate a group photo of multiple machine characters."""
    from google.genai import types

    machine_descs = []
    for i, m in enumerate(machines, 1):
        machine_descs.append(f"Machine {i}: {m['name']} ({m['type']}) — {m['personality']}. {m.get('description', '')}")

    machines_text = "\n".join(machine_descs)

    bg_desc = {
        "toolgini_workshop": "professional dark workshop with pegboard wall, tools, TOOLGINI sign on brick wall, warm lighting, sawdust",
        "modern_showroom": "clean modern showroom with spotlights, polished floor",
        "trade_show": "trade show exhibition booth with TOOLGINI banners, bright hall",
        "studio": "dark studio background with dramatic rim lighting",
    }.get(background, "warm woodworking workshop with TOOLGINI sign")

    prompt = (
        f"Pixar-style 3D render of {len(machines)} woodworking machine characters standing together "
        f"in a {bg_desc} like a team photo.\n"
        f"{machines_text}\n"
        f"Each machine has expressive cartoon eyes with eyebrows, a defined mouth, and unique personality. "
        f"Sawdust on wooden floor, warm cinematic lighting, group portrait composition. "
        f"Ultra-detailed Pixar quality 3D render."
    )

    print(f"[DEBUG] Group prompt ({len(prompt)} chars): {prompt[:400]}...")

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=[prompt],
                config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])
            )
            if (response.candidates and response.candidates[0].content
                    and response.candidates[0].content.parts):
                for part in response.candidates[0].content.parts:
                    if part.inline_data is not None:
                        return part.inline_data.data, part.inline_data.mime_type
            if attempt < 2:
                time.sleep(3)
                continue
            return None, None
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
                continue
            return None, None

    return None, None


TOOLGINI_TEAM = [
    {"name": "Best Seller", "type": "compact edgebander", "personality": "confident, energetic, small but mighty",
     "description": "small white-orange automatic edge banding machine with digital displays"},
    {"name": "Ο Μπαρμπέρης", "type": "planer/thicknesser", "personality": "wise old craftsman with mustache",
     "description": "large green industrial planer machine"},
    {"name": "Robocop", "type": "format saw", "personality": "precise, authoritative, no-nonsense",
     "description": "silver-blue panel saw with precision fence"},
    {"name": "Η Μπαλαρίνα", "type": "spindle moulder", "personality": "elegant, artistic, graceful",
     "description": "cream-colored spindle moulder with elegant curves"},
    {"name": "Ο Διαιτολόγος", "type": "dust collector", "personality": "health-obsessed, eager, always hungry for dust",
     "description": "white-green industrial dust collector with large hose"},
]


def parse_response(text):
    """Extract JSON from Gemini response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    print("Error: Could not parse JSON from response")
    return None


def save_outputs(data, output_dir, input_name, generated_images=None):
    """Save all files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Analysis JSON
    (output_dir / "analysis.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Individual prompt files
    count = 0
    for style in STYLES:
        for expr in EXPRESSIONS:
            prompt = data.get("prompts", {}).get(style, {}).get(expr, "")
            if prompt:
                (output_dir / f"{style}_{expr}.txt").write_text(prompt, encoding="utf-8")
                count += 1

    # Animation prompt
    anim = data.get("animation_prompt", "")
    if anim:
        (output_dir / "animation_prompt.txt").write_text(anim, encoding="utf-8")

    # Generated images
    img_count = 0
    if generated_images:
        images_dir = output_dir / "generated"
        images_dir.mkdir(exist_ok=True)
        for key, (img_data, mime) in generated_images.items():
            if img_data:
                ext = "png" if "png" in (mime or "") else "jpg"
                img_path = images_dir / f"{key}.{ext}"
                img_path.write_bytes(img_data)
                img_count += 1

    # HOW_TO_USE.txt
    how_to_use = f"""═══════════════════════════════════════════════════
  TOOLGINI TALKING OBJECTS — Οδηγίες Χρήσης
═══════════════════════════════════════════════════

ΤΙΜΗΧΆΝΗΜΑ: {data.get('machine_type', 'Unknown')}
ΠΡΟΣΩΠΙΚΟΤΗΤΑ: {data.get('personality', 'N/A')}

{'GENERATED IMAGES: ' + str(img_count) + ' εικόνες στο generated/' if img_count else ''}

ΠΩΣ ΝΑ ΧΡΗΣΙΜΟΠΟΙΗΣΕΙΣ ΤΑ PROMPTS:

1. Άνοιξε ένα από τα .txt αρχεία (π.χ. pixar_happy.txt)
2. Αντέγραψε όλο το κείμενο (Cmd+A, Cmd+C)
3. Πήγαινε στο ChatGPT / Midjourney / Flux / Leonardo AI
4. ΠΡΩΤΑ ανέβασε την ΑΡΧΙΚΗ φωτογραφία του μηχανήματος
5. Κάνε paste το prompt
6. Πάτα Generate — φτιάξε 4-5 παραλλαγές
7. Διάλεξε την καλύτερη!

ΓΙΑ ANIMATION (talking video):
1. Πάρε την καλύτερη εικόνα (generated/ ή ChatGPT)
2. Πήγαινε στο dzine.ai ή pika.art ή kling.ai
3. Ανέβασε την εικόνα
4. Χρησιμοποίησε το animation_prompt.txt ως οδηγό
5. Πρόσθεσε το script που θέλεις να πει το μηχάνημα

STYLES:
- cartoon_*.txt = Απλό, φιλικό, σαν κινούμενα σχέδια
- pixar_*.txt = Υψηλή ποιότητα 3D, σαν ταινία Pixar
- realistic_*.txt = Ρεαλιστικό, subtle πρόσωπο

ΕΚΦΡΑΣΕΙΣ:
- *_neutral.txt = Ήρεμο, σίγουρο
- *_happy.txt = Χαρούμενο, φιλικό
- *_serious.txt = Σοβαρό, εκπαιδευτικό
- *_surprised.txt = Έκπληκτο

ΚΟΣΤΟΣ:
- Ανάλυση (Gemini 2.5 Pro): ~$0.003
- Κάθε generated εικόνα: ~$0.039
- Σύνολο (3 εικόνες): ~$0.12
═══════════════════════════════════════════════════
"""
    (output_dir / "HOW_TO_USE.txt").write_text(how_to_use, encoding="utf-8")

    return count, img_count


def copy_to_clipboard(text):
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def process_single(image_path, args):
    """Process one image."""
    input_path = Path(image_path)
    input_name = input_path.stem

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = input_path.parent / f"{input_name}_talking"

    print(f"\n{'='*55}")
    print(f"  Talking Objects Maker v2 (Gemini)")
    print(f"{'='*55}")
    print(f"  Input: {input_path.name}")

    # Prepare
    print(f"  Loading image...")
    image = prepare_image(image_path)
    print(f"  Image ready ({image.size[0]}x{image.size[1]})")

    client = get_client()

    # Step 1: Analysis
    print(f"  Analyzing with Gemini 2.5 Pro...")
    start = time.time()
    raw = call_gemini_analysis(client, image, args.personality)
    elapsed = time.time() - start
    print(f"  Analysis complete ({elapsed:.1f}s)")

    data = parse_response(raw)
    if data is None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "_raw_response.txt").write_text(raw, encoding="utf-8")
        print(f"  Raw response saved to: {output_dir}/_raw_response.txt")
        # Retry once
        print(f"  Retrying analysis...")
        raw = call_gemini_analysis(client, image, args.personality)
        data = parse_response(raw)
        if data is None:
            print(f"  Failed to parse. Prompts saved as raw text.")
            return

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    # Step 2: Image generation (if not --no-generate)
    generated_images = {}
    if not args.no_generate:
        variants = args.variants
        gen_styles = STYLES if args.gen_style == "all" else [args.gen_style]
        gen_expression = args.expression

        total_gen = len(gen_styles) * variants
        print(f"\n  Generating {total_gen} images with Gemini Flash...")

        gen_idx = 0
        for style in gen_styles:
            prompt = data.get("prompts", {}).get(style, {}).get(gen_expression, "")
            if not prompt:
                continue

            for v in range(variants):
                gen_idx += 1
                label = f"{style}_{gen_expression}" + (f"_v{v+1}" if variants > 1 else "")
                print(f"    [{gen_idx}/{total_gen}] {label}...", end=" ", flush=True)

                face = data.get("face_placement", {})
                img_data, mime = generate_image(client, image, prompt, style, gen_expression, face)
                if img_data:
                    generated_images[label] = (img_data, mime)
                    print("OK")
                else:
                    print("skipped")

                # 3s delay between generations to avoid rate limits
                if gen_idx < total_gen:
                    time.sleep(3)

    # Save everything
    prompt_count, img_count = save_outputs(data, output_dir, input_name, generated_images)

    # Clipboard
    style_clip = args.style if args.style != "all" else "pixar"
    clip_prompt = data.get("prompts", {}).get(style_clip, {}).get(args.expression, "")
    clip_label = f"{style_clip}_{args.expression}"
    copied = False
    if args.clipboard and clip_prompt:
        copied = copy_to_clipboard(clip_prompt)

    # Preset
    presets = load_presets()
    machine_type = data.get("machine_type", "")
    preset = suggest_preset(machine_type, presets)

    face = data.get("face_placement", {})

    # Summary
    print(f"\n{'='*55}")
    print(f"  Ανάλυση Ολοκληρώθηκε!")
    print(f"{'='*55}")
    print(f"  Μηχάνημα: {machine_type}")
    print(f"  Προσωπικότητα: \"{data.get('personality', 'N/A')}\"")
    catchphrase = data.get("catchphrase_gr", "")
    if catchphrase:
        print(f"  Catchphrase: \"{catchphrase}\"")
    if preset and not args.personality:
        print(f"  Preset: \"{preset.get('personality', '')}\"")
    print()
    print(f"  Μάτια: {face.get('eyes', 'N/A')[:70]}")
    print(f"         Χρώμα: {face.get('eyes_color', 'N/A')}")
    print(f"  Στόμα: {face.get('mouth', 'N/A')[:70]}")
    print()
    print(f"  Φάκελος: {output_dir}/")
    print(f"  {prompt_count} prompts + 1 animation prompt")
    if img_count:
        print(f"  {img_count} generated images in generated/")
    if copied:
        print(f"  Clipboard: {clip_label}.txt")
    print()
    print(f"  Επόμενα βήματα:")
    if img_count:
        print(f"     1. Δες τις εικόνες στο generated/")
        print(f"     2. Διάλεξε την καλύτερη")
        print(f"     3. Για animation: ανέβασέ τη στο dzine.ai/pika.art")
        print(f"     4. Για περισσότερες: paste prompt σε ChatGPT/Midjourney")
    else:
        print(f"     1. Πήγαινε στο ChatGPT ή Midjourney")
        print(f"     2. Ανέβασε {input_path.name} ως reference")
        print(f"     3. Paste {'(ήδη στο clipboard!)' if copied else f'από {clip_label}.txt'}")
        print(f"     4. Generate και διάλεξε το καλύτερο!")
    print(f"{'='*55}\n")

    if args.verbose:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def process_batch(directory, args):
    dir_path = Path(directory)
    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    images = sorted(f for f in dir_path.iterdir()
                    if f.suffix.lower() in exts and not f.name.startswith("."))

    if not images:
        print(f"No images in {dir_path}")
        return

    print(f"\nBatch: {len(images)} images\n")
    for i, img in enumerate(images, 1):
        print(f"\n[{i}/{len(images)}] {img.name}")
        try:
            process_single(str(img), args)
        except Exception as e:
            print(f"  Error: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Transform machine photos into talking characters (Gemini 2.5)"
    )
    parser.add_argument("input", help="Image file (or directory with --batch)")
    parser.add_argument("--style", choices=["cartoon", "pixar", "realistic", "all"],
                        default="pixar", help="Style for clipboard (default: pixar)")
    parser.add_argument("--expression", choices=["neutral", "happy", "serious", "surprised"],
                        default="neutral", help="Expression (default: neutral)")
    parser.add_argument("--personality", help="Override personality")
    parser.add_argument("--output-dir", help="Output directory")
    parser.add_argument("--clipboard", action="store_true", default=True)
    parser.add_argument("--no-clipboard", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="Show full JSON")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--batch", action="store_true", help="Process all images in dir")

    # Image generation options
    parser.add_argument("--no-generate", action="store_true",
                        help="Skip image generation, only create text prompts")
    parser.add_argument("--gen-style", choices=["cartoon", "pixar", "realistic", "all"],
                        default="all", help="Which styles to generate images for (default: all)")
    parser.add_argument("--variants", type=int, default=1,
                        help="Number of image variants per style (default: 1, max 3)")

    args = parser.parse_args()
    if args.no_clipboard:
        args.clipboard = False
    args.variants = min(max(args.variants, 1), 3)

    if args.batch:
        process_batch(args.input, args)
    else:
        process_single(args.input, args)


if __name__ == "__main__":
    main()
