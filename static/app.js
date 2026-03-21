// ── Particles ──────────────────────────────────
function initParticles() {
    const container = document.querySelector('.particles');
    if (!container) return;
    for (let i = 0; i < 25; i++) {
        const p = document.createElement('div');
        p.className = 'particle';
        const size = 2 + Math.random() * 4;
        const opacity = 0.1 + Math.random() * 0.25;
        const duration = 8 + Math.random() * 14;
        const delay = Math.random() * duration;
        const left = Math.random() * 100;
        p.style.cssText = `
            width:${size}px; height:${size}px;
            left:${left}%; bottom:-10px;
            --p-opacity:${opacity};
            animation-duration:${duration}s;
            animation-delay:-${delay}s;
        `;
        container.appendChild(p);
    }
}

// ── Elements ───────────────────────────────────
const $ = id => document.getElementById(id);
const dropZone = $('drop-zone');
const fileInput = $('file-input');
const previewContainer = $('preview-container');
const previewImage = $('preview-image');
const generateBtn = $('generate-btn');
const settingsPanel = $('settings-panel');
const uploadSection = $('upload-section');
const loadingSection = $('loading-section');
const infoSection = $('info-section');
const gallerySection = $('gallery-section');
const promptsSection = $('prompts-section');
const regenSection = $('regen-section');
const errorSection = $('error-section');
const galleryGrid = $('gallery-grid');

let selectedFile = null;
let galleryImages = [];
const loadingMessagesPhoto = [
    'Analyzing object...',
    'Identifying face placement...',
    'Designing character...',
    'Generating image...',
    'Adding final touches...',
    'Almost there...'
];
const loadingMessagesText = [
    'Building character prompt...',
    'Generating image from description...',
    'Rendering character...',
    'Adding details...',
    'Almost there...'
];
const loadingMessagesGroup = [
    'Building group scene...',
    'Generating team photo...',
    'Arranging characters...',
    'Almost there...'
];
let loadingMessages = loadingMessagesPhoto;
let loadingMsgIndex = 0;
let loadingInterval = null;

// ── File handling ──────────────────────────────
if (dropZone) {
    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', e => {
        e.preventDefault(); dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', e => {
        if (e.target.files.length) handleFile(e.target.files[0]);
    });
}

function handleFile(file) {
    if (!['image/jpeg','image/png','image/webp'].includes(file.type)) { alert('Only JPG, PNG, WEBP'); return; }
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

if ($('clear-btn')) {
    $('clear-btn').addEventListener('click', () => {
        selectedFile = null;
        previewContainer.classList.add('hidden');
        dropZone.classList.remove('hidden');
        settingsPanel.classList.add('hidden');
        generateBtn.disabled = true;
        fileInput.value = '';
    });
}

// ── Generate (unified handler for all modes) ───
if (generateBtn) {
    generateBtn.addEventListener('click', async () => {
        // Common settings
        const style = $('style-select')?.value || 'pixar';
        const expr = $('expression-select')?.value || 'happy';
        const body = $('body-select')?.value || 'face_only';
        const bg = $('bg-select')?.value || 'original';
        const angle = $('angle-select')?.value || 'original';
        const customBg = $('custom-bg-input')?.value?.trim() || '';
        const clothing = $('clothing-select')?.value || 'none';
        const personality = $('personality-input')?.value?.trim() || '';

        if (currentMode === 'photo') {
            // PHOTO MODE
            if (!selectedFile) { alert('Please upload a photo first'); return; }
            const fd = new FormData();
            fd.append('image', selectedFile);
            fd.append('style', style);
            fd.append('expression', expr);
            fd.append('body_style', body);
            fd.append('background', bg);
            fd.append('camera_angle', angle);
            fd.append('custom_bg', customBg);
            fd.append('clothing', clothing);
            fd.append('generate_images', $('gen-select')?.value || 'true');
            if (personality) fd.append('personality', personality);

            showLoading();
            try {
                const res = await fetch('/upload', { method: 'POST', body: fd });
                const data = await res.json();
                stopLoading();
                if (data.error) { showError(data.error); return; }
                showMachineInfo(data);
                addToGallery(data.generated_images || {});
                showPrompts(data.prompts || {});
                showResults();
            } catch (err) { stopLoading(); showError('Network error: ' + err.message); }

        } else if (currentMode === 'text') {
            // TEXT DESCRIPTION MODE
            const desc = $('machine-description')?.value?.trim();
            if (!desc) { alert('Please describe your object'); return; }

            const fd = new FormData();
            fd.append('description', desc);
            fd.append('machine_type', $('machine-type-select')?.value || 'woodworking machine');
            fd.append('style', style);
            fd.append('expression', expr);
            fd.append('body_style', body);
            fd.append('background', bg);
            fd.append('camera_angle', angle);
            fd.append('custom_bg', customBg);
            fd.append('clothing', clothing);
            if (personality) fd.append('personality', personality);

            showLoading();
            try {
                const res = await fetch('/generate-text', { method: 'POST', body: fd });
                const data = await res.json();
                stopLoading();
                if (data.error) { showError(data.error); return; }
                if (data.machine_type) $('machine-type') && ($('machine-type').textContent = data.machine_type);
                addToGallery(data.generated_images || {});
                showResults();
            } catch (err) { stopLoading(); showError('Network error: ' + err.message); }

        } else if (currentMode === 'group') {
            // GROUP SHOT MODE
            await generateGroup();
        }
    });
}

// ── Regenerate ─────────────────────────────────
if ($('regen-btn')) {
    $('regen-btn').addEventListener('click', async () => {
        const btn = $('regen-btn');
        const fd = new FormData();
        fd.append('style', $('regen-style')?.value || 'pixar');
        fd.append('expression', $('regen-expression')?.value || 'happy');
        fd.append('body_style', $('regen-body')?.value || 'face_only');
        fd.append('background', $('regen-bg')?.value || 'original');
        fd.append('camera_angle', $('regen-angle')?.value || 'original');
        fd.append('custom_bg', $('regen-custom-bg')?.value || '');
        fd.append('clothing', $('clothing-select')?.value || 'none');

        btn.textContent = 'Generating...';
        btn.classList.add('loading');
        try {
            const res = await fetch('/regenerate', { method: 'POST', body: fd });
            const data = await res.json();
            if (data.error) { showError(data.error); }
            else { addToGallery(data.generated_images || {}); }
        } catch (err) { showError(err.message); }
        btn.textContent = 'Regenerate';
        btn.classList.remove('loading');
    });
}

if ($('new-photo-btn')) $('new-photo-btn').addEventListener('click', resetAll);

// ── Loading ────────────────────────────────────
function showLoading() {
    hideAll();
    loadingSection.classList.remove('hidden');
    uploadSection.classList.remove('hidden');
    settingsPanel.classList.add('hidden');
    // Pick right messages for mode
    if (currentMode === 'text') loadingMessages = loadingMessagesText;
    else if (currentMode === 'group') loadingMessages = loadingMessagesGroup;
    else loadingMessages = loadingMessagesPhoto;
    loadingMsgIndex = 0;
    $('loading-text').textContent = loadingMessages[0];
    loadingInterval = setInterval(() => {
        loadingMsgIndex = (loadingMsgIndex + 1) % loadingMessages.length;
        $('loading-text').textContent = loadingMessages[loadingMsgIndex];
    }, 4000);
}

function stopLoading() {
    if (loadingInterval) { clearInterval(loadingInterval); loadingInterval = null; }
}

// ── Gallery ────────────────────────────────────
function addToGallery(images) {
    let delay = 0;
    for (const [key, img] of Object.entries(images)) {
        const dataUrl = `data:${img.mime};base64,${img.data}`;
        galleryImages.push({ label: key, dataUrl });
        const card = document.createElement('div');
        card.className = 'image-card';
        card.style.animationDelay = `${delay}ms`;
        card.innerHTML = `
            <img src="${dataUrl}" alt="${key}" onclick="openLightbox('${dataUrl}')">
            <div class="card-footer">
                <span class="label">${key.replace(/_/g, ' ')}</span>
                <a href="${dataUrl}" download="${key}.png" class="btn-copy">Download</a>
            </div>
        `;
        galleryGrid.prepend(card);
        delay += 150;
    }
    if (galleryImages.length) gallerySection.classList.remove('hidden');
}

if ($('clear-gallery-btn')) {
    $('clear-gallery-btn').addEventListener('click', () => {
        galleryImages = []; galleryGrid.innerHTML = '';
        gallerySection.classList.add('hidden');
    });
}
if ($('download-all-btn')) {
    $('download-all-btn').addEventListener('click', () => { window.location.href = '/download-all'; });
}

// ── Lightbox ───────────────────────────────────
function openLightbox(src) {
    $('lightbox-img').src = src;
    $('lightbox').classList.remove('hidden');
}
function closeLightbox() { $('lightbox').classList.add('hidden'); }

// ── Machine Info ───────────────────────────────
function showMachineInfo(data) {
    $('machine-type').textContent = data.machine_type || 'Machine';
    $('personality-text').textContent = data.personality || '';
    const cp = data.catchphrase || '';
    const cpEl = $('catchphrase-text');
    cpEl.textContent = cp ? `"${cp}"` : '';
    cpEl.classList.toggle('hidden', !cp);
    const face = data.face_placement || {};
    $('eyes-info').textContent = face.eyes || 'N/A';
    $('mouth-info').textContent = face.mouth || 'N/A';
    infoSection.classList.remove('hidden');
}

// ── Prompts ────────────────────────────────────
function showPrompts(prompts) {
    const list = $('prompts-list');
    list.innerHTML = '';
    for (const [style, expressions] of Object.entries(prompts)) {
        for (const [expr, text] of Object.entries(expressions)) {
            const id = `p-${style}-${expr}-${Date.now()}`;
            const card = document.createElement('div');
            card.className = 'prompt-card';
            card.innerHTML = `
                <div class="prompt-title" onclick="togglePrompt('${id}')">${style} / ${expr} ▾</div>
                <pre id="${id}">${escapeHtml(text)}</pre>
                <button class="btn-copy" onclick="copyText('${id}',this)">Copy</button>
            `;
            list.appendChild(card);
        }
    }
    promptsSection.classList.remove('hidden');
}

function togglePrompt(id) { $(id)?.classList.toggle('expanded'); }
function toggleSection(id) { $(id)?.classList.toggle('collapsed'); }

function copyText(id, btn) {
    navigator.clipboard.writeText($(id).textContent).then(() => {
        if (btn) { btn.textContent = 'Copied!'; btn.classList.add('copied');
            setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
        }
    });
}

function escapeHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

// ── UI State ───────────────────────────────────
function hideAll() {
    [loadingSection, errorSection].forEach(s => s?.classList.add('hidden'));
}

function showResults() {
    loadingSection.classList.add('hidden');
    settingsPanel.classList.add('hidden');
    regenSection.classList.remove('hidden');
    uploadSection.classList.remove('hidden');
}

function showError(msg) {
    loadingSection.classList.add('hidden');
    $('error-text').textContent = msg;
    errorSection.classList.remove('hidden');
}

function resetAll() {
    selectedFile = null; galleryImages = [];
    galleryGrid.innerHTML = '';
    previewContainer?.classList.add('hidden');
    dropZone?.classList.remove('hidden');
    if (generateBtn) generateBtn.disabled = true;
    if (fileInput) fileInput.value = '';
    [settingsPanel, infoSection, gallerySection, promptsSection,
     regenSection, errorSection, loadingSection].forEach(s => s?.classList.add('hidden'));
}

// ── Custom BG toggle ───────────────────────────
['bg-select','regen-bg'].forEach(id => {
    const el = $(id);
    if (el) el.addEventListener('change', e => {
        const target = id === 'bg-select' ? 'custom-bg-group' : 'regen-custom-bg-group';
        $(target)?.classList.toggle('hidden', e.target.value !== 'custom');
    });
});

// ── Tabs ───────────────────────────────────────
let currentMode = 'photo';

function switchTab(mode) {
    currentMode = mode;
    document.querySelectorAll('.mode-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.add('hidden'));
    event.target.classList.add('active');
    const tab = $('tab-' + mode);
    if (tab) tab.classList.remove('hidden');

    if (settingsPanel) {
        if (mode === 'group') {
            // Group has its own generate button inside the tab
            settingsPanel.classList.add('hidden');
        } else {
            // Photo and text both use the settings panel + main generate button
            settingsPanel.classList.remove('hidden');
        }
    }

    if (generateBtn) {
        if (mode === 'text') {
            generateBtn.textContent = 'Generate from Description';
            generateBtn.disabled = false;
        } else if (mode === 'group') {
            // Group uses its own button
        } else {
            generateBtn.textContent = 'Generate!';
            generateBtn.disabled = !selectedFile;
        }
    }
}

// Text/group mode handled in unified generate handler above

// Group shot
function addGroupMachine() {
    const container = $('group-machines');
    if (!container) return;
    const card = document.createElement('div');
    card.className = 'group-machine-card';
    card.innerHTML = `
        <input type="text" placeholder="Machine name" class="gm-name">
        <input type="text" placeholder="Type" class="gm-type">
        <input type="text" placeholder="Personality" class="gm-personality">
        <input type="text" placeholder="Description" class="gm-desc">
    `;
    container.appendChild(card);
}

function loadToolginiTeam() {
    const team = [
        {name:'Best Seller', type:'compact edgebander', personality:'confident, energetic', desc:'small white-orange automatic edge banding machine'},
        {name:'Ο Μπαρμπέρης', type:'planer', personality:'wise old craftsman', desc:'large green industrial planer'},
        {name:'Robocop', type:'format saw', personality:'precise, authoritative', desc:'silver-blue panel saw'},
        {name:'Η Μπαλαρίνα', type:'spindle moulder', personality:'elegant, artistic', desc:'cream spindle moulder'},
        {name:'Ο Διαιτολόγος', type:'dust collector', personality:'health-obsessed, eager', desc:'white-green dust collector'},
    ];
    const container = $('group-machines');
    if (!container) return;
    container.innerHTML = '';
    team.forEach(m => {
        const card = document.createElement('div');
        card.className = 'group-machine-card';
        card.innerHTML = `
            <input type="text" value="${m.name}" class="gm-name">
            <input type="text" value="${m.type}" class="gm-type">
            <input type="text" value="${m.personality}" class="gm-personality">
            <input type="text" value="${m.desc}" class="gm-desc">
        `;
        container.appendChild(card);
    });
}

async function generateGroup() {
    const cards = document.querySelectorAll('.group-machine-card');
    const machines = [];
    cards.forEach(card => {
        const name = card.querySelector('.gm-name')?.value?.trim();
        const type = card.querySelector('.gm-type')?.value?.trim();
        if (name && type) {
            machines.push({
                name, type,
                personality: card.querySelector('.gm-personality')?.value?.trim() || 'friendly',
                description: card.querySelector('.gm-desc')?.value?.trim() || '',
            });
        }
    });
    if (machines.length < 2) { alert('Need at least 2 machines'); return; }

    showLoading();
    try {
        const res = await fetch('/generate-group', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                machines,
                background: $('bg-select')?.value || 'toolgini_workshop',
                camera_angle: $('angle-select')?.value || 'front_facing',
            })
        });
        const data = await res.json();
        stopLoading();
        if (data.error) { showError(data.error); return; }
        addToGallery(data.generated_images || {});
        if (gallerySection) gallerySection.classList.remove('hidden');
    } catch (err) {
        stopLoading();
        showError(err.message);
    }
}

// ── Init ───────────────────────────────────────
document.addEventListener('DOMContentLoaded', initParticles);
