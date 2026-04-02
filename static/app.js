/**
 * XHS Extractor - Frontend Logic
 */

let currentData = null;
let lightboxIndex = 0;

// ---- Extract ----

async function handleExtract() {
    const url = document.getElementById('urlInput').value.trim();
    if (!url) {
        showError('请输入小红书笔记链接');
        return;
    }

    setLoading(true);
    hideError();
    document.getElementById('resultSection').style.display = 'none';
    document.getElementById('summaryCard').style.display = 'none';

    try {
        const resp = await fetch('/api/extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
        const data = await resp.json();

        if (!resp.ok) {
            showError(data.error || '提取失败');
            return;
        }

        currentData = data;
        renderResult(data);
    } catch (err) {
        showError('网络错误: ' + err.message);
    } finally {
        setLoading(false);
    }
}

function setLoading(loading) {
    const btn = document.getElementById('extractBtn');
    btn.querySelector('.btn-text').style.display = loading ? 'none' : 'inline';
    btn.querySelector('.btn-loading').style.display = loading ? 'inline-flex' : 'none';
    btn.disabled = loading;
}

// ---- Render Result ----

function renderResult(data) {
    // Title & author
    document.getElementById('noteTitle').textContent = data.title || '(无标题)';
    document.getElementById('authorName').textContent = data.author ? `@${data.author}` : '';

    // Avatar
    const avatarEl = document.getElementById('authorAvatar');
    if (data.avatar) {
        avatarEl.src = `/api/proxy-image?url=${encodeURIComponent(data.avatar)}`;
        avatarEl.style.display = 'block';
    } else {
        avatarEl.style.display = 'none';
    }

    // Description
    document.getElementById('noteDesc').textContent = data.desc || '';

    // Tags
    const tagsContainer = document.getElementById('noteTags');
    tagsContainer.innerHTML = '';
    (data.tags || []).forEach(tag => {
        const el = document.createElement('span');
        el.className = 'tag';
        el.textContent = `#${tag}`;
        tagsContainer.appendChild(el);
    });

    // Stats
    document.getElementById('statLikes').textContent = formatNum(data.likes);
    document.getElementById('statCollects').textContent = formatNum(data.collects);
    document.getElementById('statComments').textContent = formatNum(data.comments);

    // Images
    const gallery = document.getElementById('imageGallery');
    gallery.innerHTML = '';
    (data.images || []).forEach((imgUrl, i) => {
        const proxiedUrl = `/api/proxy-image?url=${encodeURIComponent(imgUrl)}`;
        const item = document.createElement('div');
        item.className = 'image-item';
        item.onclick = (e) => {
            if (!e.target.classList.contains('image-download-btn')) {
                openLightbox(i);
            }
        };
        item.innerHTML = `
            <img src="${proxiedUrl}" alt="图片 ${i + 1}" loading="lazy">
            <span class="image-index">${i + 1}</span>
            <button class="image-download-btn" onclick="downloadSingle(${i}, event)" title="下载此图">↓</button>
        `;
        gallery.appendChild(item);
    });

    document.getElementById('resultSection').style.display = 'block';
    // Smooth scroll to results
    document.getElementById('resultSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ---- Copy Text ----

function copyText() {
    if (!currentData) return;
    const text = [
        currentData.title,
        '',
        currentData.desc,
        '',
        (currentData.tags || []).map(t => `#${t}`).join(' '),
    ].join('\n').trim();

    navigator.clipboard.writeText(text).then(() => {
        showToast('已复制到剪贴板 ✦');
    }).catch(() => {
        // Fallback
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('已复制到剪贴板 ✦');
    });
}

// ---- Download ----

async function downloadAll() {
    if (!currentData || !currentData.images?.length) return;

    showToast('正在打包下载...');

    try {
        const resp = await fetch('/api/download-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                images: currentData.images,
                title: currentData.title || 'xhs_images',
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            showError(err.error || '下载失败');
            return;
        }

        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${currentData.title || 'xhs_images'}.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('下载完成 ✦');
    } catch (err) {
        showError('下载失败: ' + err.message);
    }
}

function downloadSingle(index, event) {
    if (event) event.stopPropagation();
    if (!currentData?.images?.[index]) return;

    const imgUrl = currentData.images[index];
    const proxiedUrl = `/api/proxy-image?url=${encodeURIComponent(imgUrl)}`;

    const a = document.createElement('a');
    a.href = proxiedUrl;
    a.download = `${currentData.title || 'xhs'}_${index + 1}.jpg`;
    a.target = '_blank';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

// ---- AI Summary ----

async function handleSummarize() {
    if (!currentData) return;

    const card = document.getElementById('summaryCard');
    const loading = document.getElementById('summaryLoading');
    const textEl = document.getElementById('summaryText');

    card.style.display = 'block';
    loading.style.display = 'flex';
    textEl.textContent = '';
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });

    try {
        const resp = await fetch('/api/summarize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: currentData.title,
                desc: currentData.desc,
                tags: currentData.tags,
            }),
        });
        const data = await resp.json();

        if (!resp.ok) {
            textEl.textContent = `❌ ${data.error || '总结失败'}`;
            return;
        }

        textEl.textContent = data.summary;
    } catch (err) {
        textEl.textContent = `❌ 网络错误: ${err.message}`;
    } finally {
        loading.style.display = 'none';
    }
}

// ---- Lightbox ----

function openLightbox(index) {
    if (!currentData?.images?.length) return;
    lightboxIndex = index;
    updateLightbox();
    document.getElementById('lightbox').style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function closeLightbox(event) {
    if (event && event.target !== event.currentTarget && !event.target.classList.contains('lightbox-close')) return;
    document.getElementById('lightbox').style.display = 'none';
    document.body.style.overflow = '';
}

function navigateLightbox(direction, event) {
    if (event) event.stopPropagation();
    const total = currentData.images.length;
    lightboxIndex = (lightboxIndex + direction + total) % total;
    updateLightbox();
}

function updateLightbox() {
    const imgUrl = currentData.images[lightboxIndex];
    document.getElementById('lightboxImg').src = `/api/proxy-image?url=${encodeURIComponent(imgUrl)}`;
    document.getElementById('lightboxCurrent').textContent = lightboxIndex + 1;
    document.getElementById('lightboxTotal').textContent = currentData.images.length;
}

// Keyboard navigation
document.addEventListener('keydown', (e) => {
    const lightbox = document.getElementById('lightbox');
    if (lightbox.style.display === 'none') {
        if (e.key === 'Enter') handleExtract();
        return;
    }
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') navigateLightbox(-1);
    if (e.key === 'ArrowRight') navigateLightbox(1);
});

// ---- Helpers ----

function showError(msg) {
    document.getElementById('errorText').textContent = msg;
    document.getElementById('errorBox').style.display = 'flex';
}

function hideError() {
    document.getElementById('errorBox').style.display = 'none';
}

function formatNum(n) {
    if (n === undefined || n === null) return '0';
    n = parseInt(n);
    if (n >= 10000) return (n / 10000).toFixed(1) + '万';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return n.toString();
}

function showToast(msg) {
    // Remove existing
    document.querySelectorAll('.toast').forEach(t => t.remove());

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = msg;
    document.body.appendChild(toast);

    requestAnimationFrame(() => {
        toast.classList.add('show');
    });

    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 2500);
}
