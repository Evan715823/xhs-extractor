/**
 * XHS Extractor - Frontend Logic (Editorial Curator Edition)
 * Features: extract, batch, paste-to-extract, history, video quality,
 *           comments, dark mode, download progress, mobile gestures, abort
 */

let currentData = null;
let lightboxIndex = 0;
let extractController = null;
const HISTORY_KEY = 'xhs_extract_history';
const HISTORY_MAX = 20;
const THEME_KEY = 'xhs_theme';

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
    loadHistory();
    loadTheme();
    setupPasteHandler();
    setupSwipeGestures();
});

// ===== Theme (Dark Mode) =====

function loadTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
    }
    updateThemeIcon();
}

function toggleTheme() {
    const html = document.documentElement;
    const isDark = html.classList.contains('dark');
    if (isDark) {
        html.classList.remove('dark');
        localStorage.setItem(THEME_KEY, 'light');
    } else {
        html.classList.add('dark');
        localStorage.setItem(THEME_KEY, 'dark');
    }
    updateThemeIcon();
}

function updateThemeIcon() {
    const btn = document.getElementById('themeToggle');
    if (!btn) return;
    const isDark = document.documentElement.classList.contains('dark');
    const icon = btn.querySelector('.material-symbols-outlined');
    if (icon) {
        icon.textContent = isDark ? 'light_mode' : 'dark_mode';
    }
    btn.title = isDark ? '切换亮色' : '切换暗色';
}

// ===== Paste-to-Extract =====

function setupPasteHandler() {
    const input = document.getElementById('urlInput');
    if (!input) return;
    input.addEventListener('paste', () => {
        setTimeout(() => {
            const val = input.value.trim();
            if (val && (val.includes('xhslink.com') || val.includes('xiaohongshu.com'))) {
                handleExtract();
            }
        }, 100);
    });
}

// ===== Extract =====

async function handleExtract() {
    const input = document.getElementById('urlInput');
    const url = input.value.trim();
    if (!url) {
        showError('请输入小红书笔记链接');
        return;
    }

    const lines = url.split('\n').map(l => l.trim()).filter(l => l);
    if (lines.length > 1) {
        handleBatchExtract(lines);
        return;
    }

    if (extractController) {
        extractController.abort();
    }
    extractController = new AbortController();

    setLoading(true);
    hideError();
    document.getElementById('resultSection').style.display = 'none';
    document.getElementById('summaryCard').style.display = 'none';

    try {
        const resp = await fetch('/api/extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: lines[0] }),
            signal: extractController.signal,
        });
        const data = await resp.json();

        if (!resp.ok) {
            showError(data.error || '提取失败');
            return;
        }

        currentData = data;
        renderResult(data);
        saveToHistory(data);
    } catch (err) {
        if (err.name === 'AbortError') return;
        showError('网络错误: ' + err.message);
    } finally {
        setLoading(false);
        extractController = null;
    }
}

async function handleBatchExtract(urls) {
    if (urls.length > 10) {
        showError('一次最多提取10个链接');
        return;
    }

    setLoading(true);
    hideError();
    document.getElementById('resultSection').style.display = 'none';

    try {
        const resp = await fetch('/api/batch-extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls }),
        });
        const data = await resp.json();

        if (!resp.ok) {
            showError(data.error || '批量提取失败');
            return;
        }

        const successes = data.results.filter(r => r.success);
        const failures = data.results.filter(r => !r.success);

        if (successes.length === 0) {
            showError('所有链接提取失败');
            return;
        }

        currentData = successes[0].data;
        currentData._batch = data.results;
        renderResult(successes[0].data);

        if (failures.length > 0) {
            showToast(`${successes.length} 篇成功，${failures.length} 篇失败`);
        } else {
            showToast(`${successes.length} 篇全部提取成功`);
        }

        successes.forEach(r => saveToHistory(r.data));
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
    if (loading) {
        btn.style.opacity = '0.8';
    } else {
        btn.style.opacity = '1';
    }
}

// ===== Render Result =====

function renderResult(data) {
    document.getElementById('noteTitle').textContent = data.title || '(无标题)';
    document.getElementById('authorName').textContent = data.author ? `@${data.author}` : '';

    const avatarEl = document.getElementById('authorAvatar');
    if (data.avatar) {
        avatarEl.src = `/api/proxy-image?url=${encodeURIComponent(data.avatar)}`;
        avatarEl.style.display = 'block';
    } else {
        avatarEl.style.display = 'none';
    }

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
    document.getElementById('statComments').textContent = formatNum(data.comments_count);

    // Video vs Images
    const isVideo = data.type === 'video' && data.video_url;
    const videoSection = document.getElementById('videoSection');
    const imageSection = document.getElementById('imageSection');

    if (isVideo) {
        videoSection.style.display = 'block';
        imageSection.style.display = 'none';
        const videoPlayer = document.getElementById('videoPlayer');
        videoPlayer.src = `/api/proxy-video?url=${encodeURIComponent(data.video_url)}`;
        videoPlayer.load();
        renderVideoQuality(data.video_streams || []);
    } else {
        videoSection.style.display = 'none';
        imageSection.style.display = 'block';
    }

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
            <button class="image-download-btn" onclick="downloadSingle(${i}, event)" title="下载此图" aria-label="下载图片 ${i + 1}">
                <span class="material-symbols-outlined" style="font-size: 18px;">download</span>
            </button>
        `;
        gallery.appendChild(item);
    });

    // Comments
    renderComments(data.comments || []);

    document.getElementById('resultSection').style.display = 'block';
    document.getElementById('resultSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ===== Video Quality =====

function renderVideoQuality(streams) {
    const container = document.getElementById('videoQuality');
    if (!container) return;

    if (!streams || streams.length === 0) {
        container.style.display = 'none';
        return;
    }

    // Deduplicate by height first
    const seen = new Set();
    const unique = [];
    streams.forEach(s => {
        const key = `${s.height}p`;
        if (!seen.has(key)) {
            seen.add(key);
            unique.push(s);
        }
    });

    // Hide if only one quality available
    if (unique.length <= 1) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';
    container.innerHTML = '<span class="quality-label">画质：</span>';
    unique.forEach((s, i) => {
        const btn = document.createElement('button');
        btn.className = 'quality-btn' + (i === 0 ? ' quality-btn-active' : '');
        btn.textContent = s.label;
        btn.onclick = () => {
            container.querySelectorAll('.quality-btn').forEach(b => b.classList.remove('quality-btn-active'));
            btn.classList.add('quality-btn-active');
            switchVideoQuality(s.url);
        };
        container.appendChild(btn);
    });
}

function switchVideoQuality(url) {
    const player = document.getElementById('videoPlayer');
    const currentTime = player.currentTime;
    player.src = `/api/proxy-video?url=${encodeURIComponent(url)}`;
    player.load();
    player.addEventListener('loadeddata', () => {
        player.currentTime = currentTime;
        player.play();
    }, { once: true });
    if (currentData) currentData.video_url = url;
    showToast('切换画质中...');
}

// ===== Comments =====

function renderComments(comments) {
    const section = document.getElementById('commentsSection');
    if (!section) return;

    if (!comments || comments.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';
    const list = document.getElementById('commentsList');
    list.innerHTML = '';

    comments.forEach(c => {
        const div = document.createElement('div');
        div.className = 'comment-item';
        div.innerHTML = `
            <span class="comment-user">${escapeHtml(c.user)}</span>
            <span class="comment-text">${escapeHtml(c.content)}</span>
            ${c.likes ? `<span class="comment-likes">&#10084; ${formatNum(c.likes)}</span>` : ''}
        `;
        list.appendChild(div);
    });
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ===== History =====

function saveToHistory(data) {
    let history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    const entry = {
        note_id: data.note_id,
        title: data.title || '(无标题)',
        author: data.author || '',
        cover: data.images?.[0] || '',
        type: data.type || 'normal',
        time: Date.now(),
    };
    history = history.filter(h => h.note_id !== entry.note_id);
    history.unshift(entry);
    if (history.length > HISTORY_MAX) history = history.slice(0, HISTORY_MAX);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    loadHistory();
}

function loadHistory() {
    const container = document.getElementById('historyList');
    if (!container) return;

    const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    const section = document.getElementById('historySection');

    if (history.length === 0) {
        if (section) section.style.display = 'none';
        return;
    }

    if (section) section.style.display = 'block';
    container.innerHTML = '';

    history.slice(0, 8).forEach(h => {
        const div = document.createElement('div');
        div.className = 'history-item';
        div.onclick = () => {
            document.getElementById('urlInput').value = `https://www.xiaohongshu.com/explore/${h.note_id}`;
            handleExtract();
        };

        const coverUrl = h.cover ? `/api/proxy-image?url=${encodeURIComponent(h.cover)}` : '';
        div.innerHTML = `
            ${coverUrl ? `<img class="history-cover" src="${coverUrl}" alt="" loading="lazy">` : '<div class="history-cover history-cover-empty"></div>'}
            <div class="history-info">
                <span class="history-title">${escapeHtml(h.title)}</span>
                <span class="history-meta">${h.type === 'video' ? '&#9654; ' : ''}${escapeHtml(h.author)}</span>
            </div>
        `;
        container.appendChild(div);
    });
}

function clearHistory() {
    localStorage.removeItem(HISTORY_KEY);
    loadHistory();
    showToast('历史已清空');
}

// ===== Copy Text =====

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
        showToast('已复制到剪贴板');
    }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('已复制到剪贴板');
    });
}

// ===== Download =====

async function downloadAll() {
    if (!currentData || !currentData.images?.length) return;

    const progressBar = document.getElementById('downloadProgress');
    if (progressBar) progressBar.style.display = 'block';
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

        const contentLength = +resp.headers.get('Content-Length') || 0;
        const reader = resp.body.getReader();
        const chunks = [];
        let received = 0;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            chunks.push(value);
            received += value.length;
            if (contentLength && progressBar) {
                const pct = Math.min(100, (received / contentLength) * 100);
                progressBar.querySelector('.progress-fill').style.width = pct + '%';
            }
        }

        const blob = new Blob(chunks);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${currentData.title || 'xhs_images'}.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        const failedCount = resp.headers.get('X-Failed-Count');
        if (failedCount && parseInt(failedCount) > 0) {
            showToast(`下载完成，${failedCount} 张图片失败`);
        } else {
            showToast('下载完成');
        }
    } catch (err) {
        showError('下载失败: ' + err.message);
    } finally {
        if (progressBar) {
            progressBar.style.display = 'none';
            progressBar.querySelector('.progress-fill').style.width = '0%';
        }
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

async function downloadVideo() {
    if (!currentData?.video_url) return;

    const progressBar = document.getElementById('downloadProgress');
    if (progressBar) progressBar.style.display = 'block';
    showToast('正在下载视频...');

    try {
        const proxiedUrl = `/api/proxy-video?url=${encodeURIComponent(currentData.video_url)}`;
        const resp = await fetch(proxiedUrl);

        if (!resp.ok) {
            showError('视频下载失败');
            return;
        }

        const contentLength = +resp.headers.get('Content-Length') || 0;
        const reader = resp.body.getReader();
        const chunks = [];
        let received = 0;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            chunks.push(value);
            received += value.length;
            if (contentLength && progressBar) {
                const pct = Math.min(100, (received / contentLength) * 100);
                progressBar.querySelector('.progress-fill').style.width = pct + '%';
                const mb = (received / 1024 / 1024).toFixed(1);
                const totalMb = (contentLength / 1024 / 1024).toFixed(1);
                progressBar.querySelector('.progress-text').textContent = `${mb}MB / ${totalMb}MB`;
            }
        }

        const blob = new Blob(chunks, { type: 'video/mp4' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const safeTitle = (currentData.title || 'xhs_video').replace(/[^\w\u4e00-\u9fff _-]/g, '').slice(0, 50);
        a.download = `${safeTitle}.mp4`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('视频下载完成');
    } catch (err) {
        showError('视频下载失败: ' + err.message);
    } finally {
        if (progressBar) {
            progressBar.style.display = 'none';
            progressBar.querySelector('.progress-fill').style.width = '0%';
            progressBar.querySelector('.progress-text').textContent = '';
        }
    }
}

// ===== AI Summary =====

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
            textEl.textContent = data.error || '总结失败';
            return;
        }

        textEl.textContent = data.summary;
    } catch (err) {
        textEl.textContent = '网络错误: ' + err.message;
    } finally {
        loading.style.display = 'none';
    }
}

// ===== Lightbox =====

function openLightbox(index) {
    if (!currentData?.images?.length) return;
    lightboxIndex = Math.min(index, currentData.images.length - 1);
    updateLightbox();
    document.getElementById('lightbox').style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function closeLightbox(event) {
    if (event && event.target !== event.currentTarget && !event.target.closest('[onclick*="closeLightbox"]')) return;
    document.getElementById('lightbox').style.display = 'none';
    document.body.style.overflow = '';
}

function navigateLightbox(direction, event) {
    if (event) event.stopPropagation();
    if (!currentData?.images?.length) return;
    const total = currentData.images.length;
    lightboxIndex = (lightboxIndex + direction + total) % total;
    updateLightbox();
}

function updateLightbox() {
    if (!currentData?.images?.length) return;
    const imgUrl = currentData.images[lightboxIndex];
    document.getElementById('lightboxImg').src = `/api/proxy-image?url=${encodeURIComponent(imgUrl)}`;
    document.getElementById('lightboxCurrent').textContent = lightboxIndex + 1;
    document.getElementById('lightboxTotal').textContent = currentData.images.length;
}

// ===== Mobile Swipe Gestures =====

function setupSwipeGestures() {
    const lightbox = document.getElementById('lightbox');
    if (!lightbox) return;

    let touchStartX = 0;
    let touchStartY = 0;

    lightbox.addEventListener('touchstart', (e) => {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
    }, { passive: true });

    lightbox.addEventListener('touchend', (e) => {
        const dx = e.changedTouches[0].clientX - touchStartX;
        const dy = e.changedTouches[0].clientY - touchStartY;
        if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) {
            if (dx > 0) navigateLightbox(-1);
            else navigateLightbox(1);
        }
    }, { passive: true });
}

// ===== Keyboard =====

document.addEventListener('keydown', (e) => {
    const lightbox = document.getElementById('lightbox');
    if (lightbox.style.display === 'none' || lightbox.style.display === '') {
        if (e.key === 'Enter' && document.activeElement?.id === 'urlInput') handleExtract();
        return;
    }
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') navigateLightbox(-1);
    if (e.key === 'ArrowRight') navigateLightbox(1);
});

// ===== Helpers =====

function showError(msg) {
    document.getElementById('errorText').textContent = msg;
    const box = document.getElementById('errorBox');
    box.style.display = 'block';
    clearTimeout(box._dismissTimer);
    box._dismissTimer = setTimeout(() => hideError(), 6000);
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
    document.querySelectorAll('.toast').forEach(t => t.remove());
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = msg;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 400);
    }, 2500);
}
