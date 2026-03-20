const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const previewContainer = document.getElementById('preview-container');
const previewImage = document.getElementById('preview-image');
const generateBtn = document.getElementById('generate-btn');
const settingsPanel = document.getElementById('settings-panel');
const uploadSection = document.getElementById('upload-section');
const loadingSection = document.getElementById('loading-section');
const infoSection = document.getElementById('info-section');
const gallerySection = document.getElementById('gallery-section');
const promptsSection = document.getElementById('prompts-section');
const regenSection = document.getElementById('regen-section');
const errorSection = document.getElementById('error-section');
const galleryGrid = document.getElementById('gallery-grid');

let selectedFile = null;
let hasAnalysis = false;
let galleryImages = []; // {label, dataUrl, jobId}

// === FILE HANDLING ===
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
    e.preventDefault(); dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', e => {
    if (e.target.files.length > 0) handleFile(e.target.files[0]);
});

function handleFile(file) {
    if (!['image/jpeg','image/png','image/webp'].includes(file.type)) {
        alert('Only JPG, PNG, WEBP accepted'); return;
    }
    if (file.size > 20*1024*1024) { alert('Max 20MB'); return; }
    selectedFile = file;
    const reader = new FileReader();
    reader.onload = e => {
        previewImage.src = e.target.result;
        previewContainer.classList.remove('hidden');
        dropZone.classList.add('hidden');
        settingsPanel.classList.remove('hidden');
        generateBtn.disabled = false;
    };
    reader.readAsDataURL(file);
}

document.getElementById('clear-btn').addEventListener('click', () => {
    selectedFile = null;
    previewContainer.classList.add('hidden');
    dropZone.classList.remove('hidden');
    settingsPanel.classList.add('hidden');
    generateBtn.disabled = true;
    fileInput.value = '';
});

// === GENERATE (first upload) ===
generateBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    const formData = new FormData();
    formData.append('image', selectedFile);
    formData.append('style', document.getElementById('style-select').value);
    formData.append('expression', document.getElementById('expression-select').value);
    formData.append('body_style', document.getElementById('body-select').value);
    formData.append('background', document.getElementById('bg-select').value);
    formData.append('camera_angle', document.getElementById('angle-select').value);
    formData.append('custom_bg', document.getElementById('custom-bg-input').value.trim());
    formData.append('generate_images', document.getElementById('gen-select').value);
    const personality = document.getElementById('personality-input').value.trim();
    if (personality) formData.append('personality', personality);

    showLoading('Analyzing machine...', 'Phase 1: Gemini 2.5 Pro analysis (30-60s)');

    try {
        const res = await fetch('/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.error) { showError(data.error); return; }

        hasAnalysis = true;
        showMachineInfo(data);
        addToGallery(data.generated_images || {});
        showPrompts(data.prompts || {});
        showResults();
    } catch (err) {
        showError('Network error: ' + err.message);
    }
});

// === REGENERATE ===
document.getElementById('regen-btn').addEventListener('click', async () => {
    const formData = new FormData();
    formData.append('style', document.getElementById('regen-style').value);
    formData.append('expression', document.getElementById('regen-expression').value);
    formData.append('body_style', document.getElementById('regen-body').value);
    formData.append('background', document.getElementById('regen-bg').value);
    formData.append('camera_angle', document.getElementById('regen-angle').value);
    formData.append('custom_bg', (document.getElementById('regen-custom-bg') || {}).value || '');

    const btn = document.getElementById('regen-btn');
    btn.textContent = 'Generating...';
    btn.classList.add('loading');

    try {
        const res = await fetch('/regenerate', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.error) { showError(data.error); btn.textContent = 'Regenerate'; btn.classList.remove('loading'); return; }

        addToGallery(data.generated_images || {});
        btn.textContent = 'Regenerate';
        btn.classList.remove('loading');
    } catch (err) {
        showError('Network error: ' + err.message);
        btn.textContent = 'Regenerate';
        btn.classList.remove('loading');
    }
});

document.getElementById('new-photo-btn').addEventListener('click', resetAll);

// Custom background toggle
document.getElementById('bg-select').addEventListener('change', e => {
    document.getElementById('custom-bg-group').classList.toggle('hidden', e.target.value !== 'custom');
});
document.getElementById('regen-bg').addEventListener('change', e => {
    document.getElementById('regen-custom-bg-group').classList.toggle('hidden', e.target.value !== 'custom');
});

// === GALLERY ===
function addToGallery(images) {
    for (const [key, img] of Object.entries(images)) {
        const dataUrl = `data:${img.mime};base64,${img.data}`;
        galleryImages.push({ label: key.replace(/_/g, ' '), dataUrl });

        const card = document.createElement('div');
        card.className = 'image-card';
        card.innerHTML = `
            <img src="${dataUrl}" alt="${key}" onclick="openLightbox('${dataUrl}')">
            <div class="card-footer">
                <span class="label">${key.replace(/_/g, ' ')}</span>
                <a href="${dataUrl}" download="${key}.png" class="btn-copy">Download</a>
            </div>
        `;
        galleryGrid.appendChild(card);
    }

    if (galleryImages.length > 0) {
        gallerySection.classList.remove('hidden');
    }
}

document.getElementById('clear-gallery-btn').addEventListener('click', () => {
    galleryImages = [];
    galleryGrid.innerHTML = '';
    gallerySection.classList.add('hidden');
});

document.getElementById('download-all-btn').addEventListener('click', () => {
    window.location.href = '/download-all';
});

// === LIGHTBOX ===
function openLightbox(src) {
    document.getElementById('lightbox-img').src = src;
    document.getElementById('lightbox').classList.remove('hidden');
}
function closeLightbox() {
    document.getElementById('lightbox').classList.add('hidden');
}

// === MACHINE INFO ===
function showMachineInfo(data) {
    document.getElementById('machine-type').textContent = data.machine_type || 'Machine';
    document.getElementById('personality-text').textContent = data.personality || '';
    const cp = data.catchphrase || '';
    const cpEl = document.getElementById('catchphrase-text');
    cpEl.textContent = cp ? `"${cp}"` : '';
    cpEl.classList.toggle('hidden', !cp);

    const face = data.face_placement || {};
    document.getElementById('eyes-info').textContent = face.eyes || 'N/A';
    document.getElementById('mouth-info').textContent = face.mouth || 'N/A';

    infoSection.classList.remove('hidden');
}

// === PROMPTS ===
function showPrompts(prompts) {
    const list = document.getElementById('prompts-list');
    list.innerHTML = '';
    for (const [style, expressions] of Object.entries(prompts)) {
        for (const [expr, text] of Object.entries(expressions)) {
            const id = `prompt-${style}-${expr}-${Date.now()}`;
            const card = document.createElement('div');
            card.className = 'prompt-card';
            card.innerHTML = `
                <div class="prompt-title" onclick="togglePrompt('${id}')">${style} / ${expr} ▾</div>
                <pre id="${id}">${escapeHtml(text)}</pre>
                <button class="btn-copy" onclick="copyText('${id}', this)">Copy</button>
            `;
            list.appendChild(card);
        }
    }
    promptsSection.classList.remove('hidden');
}

function togglePrompt(id) { document.getElementById(id).classList.toggle('expanded'); }
function toggleSection(id) { document.getElementById(id).classList.toggle('collapsed'); }

function copyText(id, btn) {
    navigator.clipboard.writeText(document.getElementById(id).textContent).then(() => {
        if (btn) { btn.textContent = 'Copied!'; btn.classList.add('copied');
            setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
        }
    });
}

function escapeHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

// === UI STATE ===
function showLoading(text, sub) {
    hideAll();
    document.getElementById('loading-text').textContent = text;
    document.getElementById('loading-sub').textContent = sub;
    loadingSection.classList.remove('hidden');
    // Keep preview visible
    uploadSection.classList.remove('hidden');
    settingsPanel.classList.add('hidden');
}

function showResults() {
    loadingSection.classList.add('hidden');
    settingsPanel.classList.add('hidden');
    regenSection.classList.remove('hidden');
    // Keep upload section with preview
    uploadSection.classList.remove('hidden');
}

function showError(msg) {
    loadingSection.classList.add('hidden');
    document.getElementById('error-text').textContent = msg;
    errorSection.classList.remove('hidden');
}

function hideAll() {
    loadingSection.classList.add('hidden');
    errorSection.classList.add('hidden');
}

function resetAll() {
    selectedFile = null; hasAnalysis = false;
    galleryImages = [];
    galleryGrid.innerHTML = '';
    previewContainer.classList.add('hidden');
    dropZone.classList.remove('hidden');
    generateBtn.disabled = true;
    fileInput.value = '';
    settingsPanel.classList.add('hidden');
    infoSection.classList.add('hidden');
    gallerySection.classList.add('hidden');
    promptsSection.classList.add('hidden');
    regenSection.classList.add('hidden');
    errorSection.classList.add('hidden');
    loadingSection.classList.add('hidden');
}
