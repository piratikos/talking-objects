# Talking Objects Maker — by Toolgini

Turn any machine or object photo into a Pixar-style talking character.

Uses Google Gemini 2.5 Pro Vision to analyze photos and generate precise image-generation prompts, then optionally generates actual images with Gemini Flash.

## Features

- **Multi-style output**: Cartoon, Pixar 3D, and Realistic styles
- **4 expressions each**: Neutral, Happy, Serious, Surprised (12 prompts total)
- **AI-powered analysis**: Gemini 2.5 Pro identifies exact face placement on any machine
- **Image generation**: Optional automatic image creation via Gemini Flash
- **Animation prompts**: Ready-to-use prompts for Kling AI, Pika, Runway
- **Batch processing**: Process entire folders of product photos
- **Personality presets**: Auto-detected personalities for common machine types
- **Web interface**: Flask-based web UI with drag-and-drop upload
- **API endpoint**: POST `/api/generate` for programmatic access
- **Clipboard support**: Selected prompt auto-copied to clipboard

## How It Works

**Phase 1 — Analysis** (~$0.003 per image)
- Sends photo to Gemini 2.5 Pro Vision
- AI analyzes every component: shape, color, materials, controls, environment
- Identifies optimal eye and mouth placement on the machine
- Generates 12 detailed prompts (3 styles x 4 expressions)

**Phase 2 — Image Generation** (~$0.039 per image, optional)
- Sends original photo + prompt to Gemini Flash
- Generates actual talking character images
- Saves to `generated/` subfolder

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/talking-objects.git
cd talking-objects
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your Gemini API key from https://aistudio.google.com/apikey
```

## Usage

### CLI

```bash
# Basic (analysis + 3 generated images):
python talking_objects.py photo.jpg

# Prompts only (fast, ~$0.003):
python talking_objects.py photo.jpg --no-generate

# Specific style and expression:
python talking_objects.py photo.jpg --style cartoon --expression happy

# Custom personality:
python talking_objects.py photo.jpg --personality "angry Greek comedian"

# Multiple variants per style:
python talking_objects.py photo.jpg --variants 3

# Batch process folder:
python talking_objects.py ./photos/ --batch --no-generate
```

### Web Interface

```bash
python web_app.py
# Open http://localhost:5050
```

### API

```bash
curl -X POST http://localhost:5050/api/generate \
  -F "image=@photo.jpg" \
  -F "style=pixar" \
  -F "expression=happy"
```

## Output

For each photo, creates a folder with:
```
photo_talking/
├── analysis.json           # Full structured analysis
├── cartoon_neutral.txt     # 12 prompt files
├── cartoon_happy.txt
├── ...
├── animation_prompt.txt    # For video tools (Kling/Pika)
├── HOW_TO_USE.txt          # Instructions in Greek
└── generated/              # AI-generated images (if enabled)
    ├── cartoon_happy.png
    ├── pixar_happy.png
    └── realistic_happy.png
```

## Cost

| Action | Model | Cost |
|--------|-------|------|
| Analysis | Gemini 2.5 Pro | ~$0.003 |
| Each generated image | Gemini Flash | ~$0.039 |
| 3 images (default) | | ~$0.12 |
| Prompts only | | ~$0.003 |

## Personality Presets

The tool auto-detects machine types and suggests personalities:

| Machine | Personality | Catchphrase |
|---------|------------|-------------|
| Edge bander | Small but mighty, energetic | Ειμαι μικρη αλλα κανω τα παντα! |
| Planer | Wise old craftsman | Εγω ξερω απο ξυλο, παιδι μου... |
| Panel saw | Precise, no-nonsense | Ακριβεια. Παντα ακριβεια. |
| Dust collector | Health-obsessed, hungry | Σκονη; Που ειναι σκονη; Θα τη φαω! |

## License

MIT License - Toolgini / Woodmachine LP
