const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const previewContainer = document.getElementById('preview-container');
const previewImage = document.getElementById('preview-image');
const generateBtn = document.getElementById('generate-btn');
const uploadSection = document.getElementById('upload-section');
const loadingSection = document.getElementById('loading-section');
const resultsSection = document.getElementById('results-section');
const errorSection = document.getElementById('error-section');

let selectedFile = null;
let currentJobId = null;

// Drag and drop
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0) handleFile(files[0]);
});
fileInput.addEventListener('change', e => {
    if (e.target.files.length > 0) handleFile(e.target.files[0]);
});

function handleFile(file) {
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
        alert('Only JPG, PNG, WEBP files accepted');
        return;
    }
    if (file.size > 20 * 1024 * 1024) {
        alert('File too large (max 20MB)');
        return;
    }
    selectedFile = file;
    const reader = new FileReader();
    reader.onload = e => {
        previewImage.src = e.target.result;
        previewContainer.classList.remove('hidden');
        dropZone.classList.add('hidden');
        generateBtn.disabled = false;
    };
    reader.readAsDataURL(file);
}

document.getElementById('clear-btn').addEventListener('click', () => {
    selectedFile = null;
    previewContainer.classList.add('hidden');
    dropZone.classList.remove('hidden');
    generateBtn.disabled = true;
    fileInput.value = '';
});

// Generate
generateBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    const formData = new FormData();
    formData.append('image', selectedFile);
    formData.append('style', document.getElementById('style-select').value);
    formData.append('expression', document.getElementById('expression-select').value);
    formData.append('generate_images', document.getElementById('gen-select').value);
    const personality = document.getElementById('personality-input').value.trim();
    if (personality) formData.append('personality', personality);

    showSection('loading');
    updateLoading('Analyzing machine...', 'Phase 1: Gemini 2.5 Pro Vision analysis (30-60s)');

    try {
        const response = await fetch('/upload', { method: 'POST', body: formData });
        const data = await response.json();

        if (data.error) {
            showError(data.error);
            return;
        }

        currentJobId = data.job_id;
        showResults(data);
    } catch (err) {
        showError('Network error: ' + err.message);
    }
});

function showSection(name) {
    uploadSection.classList.add('hidden');
    loadingSection.classList.add('hidden');
    resultsSection.classList.add('hidden');
    errorSection.classList.add('hidden');
    document.getElementById(name + '-section').classList.remove('hidden');
}

function updateLoading(text, sub) {
    document.getElementById('loading-text').textContent = text;
    document.getElementById('loading-sub').textContent = sub;
}

function showError(msg) {
    document.getElementById('error-text').textContent = msg;
    showSection('error');
}

function showResults(data) {
    // Machine info
    document.getElementById('machine-type').textContent = data.machine_type || 'Machine';
    document.getElementById('personality-text').textContent = data.personality || '';
    const catchphrase = data.catchphrase || '';
    const cpEl = document.getElementById('catchphrase-text');
    cpEl.textContent = catchphrase ? `"${catchphrase}"` : '';
    cpEl.classList.toggle('hidden', !catchphrase);

    // Face placement
    const face = data.face_placement || {};
    document.getElementById('eyes-info').textContent = face.eyes || 'N/A';
    document.getElementById('mouth-info').textContent = face.mouth || 'N/A';

    // Generated images
    const imagesGrid = document.getElementById('images-grid');
    imagesGrid.innerHTML = '';
    const genImages = data.generated_images || {};
    const hasImages = Object.keys(genImages).length > 0;

    if (hasImages) {
        imagesGrid.classList.remove('hidden');
        for (const [key, img] of Object.entries(genImages)) {
            const card = document.createElement('div');
            card.className = 'image-card';
            card.innerHTML = `
                <img src="data:${img.mime};base64,${img.data}" alt="${key}">
                <div class="label">${key.replace('_', ' ')}</div>
                <a href="/download/${currentJobId}/${key}.png" class="btn-copy" download>Download</a>
            `;
            imagesGrid.appendChild(card);
        }
    } else {
        imagesGrid.classList.add('hidden');
    }

    // Prompts
    const promptsList = document.getElementById('prompts-list');
    promptsList.innerHTML = '';
    const prompts = data.prompts || {};

    for (const [style, expressions] of Object.entries(prompts)) {
        for (const [expr, text] of Object.entries(expressions)) {
            const id = `prompt-${style}-${expr}`;
            const card = document.createElement('div');
            card.className = 'prompt-card';
            card.innerHTML = `
                <div class="prompt-title" onclick="togglePrompt('${id}')">${style} / ${expr} ▾</div>
                <pre id="${id}">${escapeHtml(text)}</pre>
                <button class="btn-copy" onclick="copyText('${id}')">Copy</button>
            `;
            promptsList.appendChild(card);
        }
    }

    // Animation
    const animSection = document.getElementById('animation-section');
    const animPrompt = data.animation_prompt || '';
    if (animPrompt) {
        document.getElementById('animation-prompt').textContent = animPrompt;
        document.getElementById('animation-prompt').classList.add('expanded');
        animSection.classList.remove('hidden');
    } else {
        animSection.classList.add('hidden');
    }

    // Download button
    const dlBtn = document.getElementById('download-all-btn');
    if (currentJobId) {
        dlBtn.classList.remove('hidden');
        dlBtn.onclick = () => window.location.href = `/download/${currentJobId}`;
    }

    showSection('results');
}

function togglePrompt(id) {
    document.getElementById(id).classList.toggle('expanded');
}

function copyText(id) {
    const el = document.getElementById(id);
    const text = el.textContent;
    navigator.clipboard.writeText(text).then(() => {
        const btn = el.nextElementSibling || el.parentElement.querySelector('.btn-copy');
        if (btn) {
            btn.textContent = 'Copied!';
            btn.classList.add('copied');
            setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
        }
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function resetUI() {
    selectedFile = null;
    currentJobId = null;
    previewContainer.classList.add('hidden');
    dropZone.classList.remove('hidden');
    generateBtn.disabled = true;
    fileInput.value = '';
    showSection('upload');
}

document.getElementById('try-again-btn').addEventListener('click', resetUI);
