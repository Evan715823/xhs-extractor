"""
小红书笔记内容抓取器
Extracts images, text, and metadata from Xiaohongshu note URLs.
"""

import json
import re
import time
from functools import lru_cache
from hashlib import md5

import httpx
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# Shared connection pool — reused across all proxy requests
_http_pool = httpx.Client(
    follow_redirects=True,
    headers={
        "User-Agent": HEADERS["User-Agent"],
        "Referer": "https://www.xiaohongshu.com/",
    },
    timeout=30,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)

# Simple TTL cache for proxied images: {url_hash: (bytes, content_type, timestamp)}
_image_cache: dict[str, tuple[bytes, str, float]] = {}
_CACHE_TTL = 3600  # 1 hour
_CACHE_MAX = 200   # max entries


def _build_headers(cookie: str = "", referer: str = "https://www.xiaohongshu.com/") -> dict:
    headers = HEADERS.copy()
    headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _retry(fn, retries=2, delay=1.0):
    """Retry a callable with exponential backoff."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            last_err = e
            if attempt < retries:
                time.sleep(delay * (2 ** attempt))
    raise last_err


def _extract_url_from_text(text: str) -> str:
    """Extract XHS URL from share text like '标题... http://xhslink.com/xxx copy and open...'"""
    match = re.search(r'https?://(?:www\.)?(?:xhslink\.com|xiaohongshu\.com)\S+', text)
    if match:
        return match.group(0).rstrip('.,;!?)\'"')
    return text.strip()


def _resolve_short_url(url: str, cookie: str = "") -> str:
    """Resolve xhslink.com short URLs to full xiaohongshu.com URLs."""
    if "xhslink.com" not in url:
        return url
    headers = _build_headers(cookie, referer="https://www.xiaohongshu.com/")

    def do_resolve():
        with httpx.Client(follow_redirects=True, headers=headers, timeout=15) as client:
            resp = client.get(url)
            return str(resp.url)

    return _retry(do_resolve)


def _extract_note_id(url: str) -> str | None:
    """Extract note_id from various XHS URL formats."""
    patterns = [
        r"/explore/([a-f0-9]+)",
        r"/discovery/item/([a-f0-9]+)",
        r"/note/([a-f0-9]+)",
        r"noteId=([a-f0-9]+)",
        r"/([a-f0-9]{24})(?:\?|$|&)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _clean_image_url(url: str) -> str:
    """Remove image processing parameters to get original quality without watermark."""
    if "?" in url:
        base = url.split("?")[0]
    else:
        base = url
    # Remove XHS image processing suffix (e.g. !h5_1080jpg, !k, @500w)
    base = re.split(r'[!@]', base)[0]
    if base.startswith("http://"):
        base = "https://" + base[7:]
    if not base.startswith("http"):
        base = "https://" + base
    return base


# CDN host that serves original images without watermark or signed URLs
_ORIGINAL_CDN = "https://sns-img-bd.xhscdn.com"


def _fix_json_text(text: str) -> str:
    """Fix XHS's non-standard JSON (undefined, NaN, Infinity, etc.)."""
    text = text.replace("undefined", "null")
    text = re.sub(r'\bNaN\b', "null", text)
    text = re.sub(r'\bInfinity\b', "null", text)
    return text


def _parse_initial_state(soup: BeautifulSoup, note_id: str) -> tuple[dict | None, dict | None]:
    """Try to extract note data and full state from __INITIAL_STATE__ script tag.
    Returns (note_data, full_state) for comment extraction.
    """
    for script in soup.find_all("script"):
        text = script.string or ""
        if "window.__INITIAL_STATE__" in text:
            json_str = text.split("window.__INITIAL_STATE__=", 1)[1]
            json_str = _fix_json_text(json_str)
            try:
                state = json.loads(json_str)
            except json.JSONDecodeError:
                return None, None

            # New structure: noteData.data.noteData
            note_data = (
                state.get("noteData", {})
                .get("data", {})
                .get("noteData")
            )
            if note_data:
                return note_data, state

            # Legacy structure: note.noteDetailMap
            note_detail_map = state.get("note", {}).get("noteDetailMap", {})
            note_data = note_detail_map.get(note_id, {}).get("note")
            if not note_data:
                for key, val in note_detail_map.items():
                    note_data = val.get("note")
                    if note_data:
                        break

            return note_data, state
    return None, None


def _extract_comments(state: dict | None) -> list[dict]:
    """Extract hot comments from __INITIAL_STATE__."""
    if not state:
        return []
    comments = []

    # Try multiple known paths for comment data
    comment_data = state.get("commentData", {}).get("data", {})
    comment_list = comment_data.get("comments", [])

    if not comment_list:
        # Legacy path
        comment_data = state.get("comment", {})
        comment_list = comment_data.get("commentList", [])

    for c in comment_list[:20]:  # Cap at 20 comments
        user = c.get("user", {}) or c.get("userInfo", {})
        content = c.get("content", "")
        nickname = user.get("nickname", "") or user.get("nickName", "")
        likes = c.get("likeCount", 0) or c.get("likes", 0)
        if content:
            comments.append({
                "user": nickname,
                "content": content,
                "likes": likes,
            })
    return comments


def _parse_meta_tags(soup: BeautifulSoup) -> dict | None:
    """Fallback: extract data from Open Graph and other meta tags."""
    def get_meta(name):
        tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
        return tag.get("content", "").strip() if tag else ""

    title = get_meta("og:title") or get_meta("title")
    desc = get_meta("og:description") or get_meta("description")
    image = get_meta("og:image")

    if not title and not desc and not image:
        return None

    images = [_clean_image_url(image)] if image else []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "")
            if isinstance(ld, dict):
                ld_images = ld.get("image", [])
                if isinstance(ld_images, str):
                    ld_images = [ld_images]
                for img in ld_images:
                    cleaned = _clean_image_url(img)
                    if cleaned not in images:
                        images.append(cleaned)
        except (json.JSONDecodeError, TypeError):
            pass

    author = get_meta("og:xhs:note:author") or get_meta("author") or ""

    return {
        "title": title,
        "desc": desc,
        "images": images,
        "author": author,
        "_from_meta": True,
    }


def _extract_xsec_token(url: str) -> str:
    """Extract xsec_token from URL query parameters."""
    match = re.search(r'[?&]xsec_token=([^&]+)', url)
    return match.group(1) if match else ""


def extract_note(url: str, cookie: str = "") -> dict:
    """
    Extract content from a Xiaohongshu note URL.
    Uses multiple fallback strategies:
    1. __INITIAL_STATE__ JSON parsing
    2. Open Graph meta tags
    """
    # Input validation
    if len(url) > 2048:
        raise ValueError("输入文本过长")

    # Extract URL from share text
    url = _extract_url_from_text(url)

    # Resolve short links (with retry)
    resolved_url = _resolve_short_url(url, cookie)
    note_id = _extract_note_id(resolved_url)
    if not note_id:
        raise ValueError(f"无法从 URL 中提取笔记ID: {resolved_url}")

    # Preserve xsec_token and xsec_source from resolved URL
    xsec_token = _extract_xsec_token(resolved_url)
    xsec_source_match = re.search(r'[?&]xsec_source=([^&]+)', resolved_url)
    xsec_source = xsec_source_match.group(1) if xsec_source_match else ""

    # Fetch the page with retry
    page_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    params = {}
    if xsec_token:
        params["xsec_token"] = xsec_token
    if xsec_source:
        params["xsec_source"] = xsec_source
    headers = _build_headers(cookie)

    def do_fetch():
        with httpx.Client(follow_redirects=True, headers=headers, timeout=20) as client:
            resp = client.get(page_url, params=params)
            resp.raise_for_status()
            return resp.text

    html = _retry(do_fetch)
    soup = BeautifulSoup(html, "lxml")

    # Strategy 1: Parse __INITIAL_STATE__
    note_data, full_state = _parse_initial_state(soup, note_id)

    if note_data:
        result = _build_result_from_state(note_data, note_id)
        result["comments"] = _extract_comments(full_state)
        return result

    # Strategy 2: Parse meta tags
    meta_data = _parse_meta_tags(soup)
    if meta_data:
        return {
            "title": meta_data["title"],
            "desc": meta_data["desc"],
            "tags": [],
            "images": meta_data["images"],
            "video_url": "",
            "video_streams": [],
            "author": meta_data["author"],
            "avatar": "",
            "likes": 0,
            "collects": 0,
            "comments_count": 0,
            "note_id": note_id,
            "type": "normal",
            "comments": [],
        }

    raise ValueError(
        f"未找到笔记数据 (note_id: {note_id})，请确认链接有效或尝试提供Cookie"
    )


def _build_result_from_state(note_data: dict, note_id: str) -> dict:
    """Build result dict from __INITIAL_STATE__ note data."""
    title = note_data.get("title", "")
    desc = note_data.get("desc", "")
    note_type = note_data.get("type", "normal")

    # Tags
    tag_list = note_data.get("tagList", [])
    tags = [t.get("name", "") for t in tag_list if t.get("name")]
    inline_tags = re.findall(r"#([^#\[\]]+?)(?:\[话题\])?#", desc)
    for t in inline_tags:
        t = t.strip()
        if t and t not in tags:
            tags.append(t)

    # Images — prefer fileId for original quality without watermark
    image_list = note_data.get("imageList", [])
    images = []
    for img in image_list:
        file_id = img.get("fileId", "")
        if file_id:
            images.append(f"{_ORIGINAL_CDN}/{file_id}")
        else:
            info_list = img.get("infoList", [])
            if info_list:
                info_list_sorted = sorted(info_list, key=lambda x: x.get("width", 0), reverse=True)
                best = info_list_sorted[0].get("url", "")
            else:
                best = img.get("urlDefault", "") or img.get("url", "")
            if best:
                images.append(_clean_image_url(best))

    # Video — collect all available streams for quality selection
    video = note_data.get("video", {})
    video_url = ""
    video_streams = []
    if video:
        media = video.get("media", {})
        stream = media.get("stream", {})
        for codec in ["h265", "h264", "av1"]:
            codec_streams = stream.get(codec, [])
            for s in codec_streams:
                url = s.get("masterUrl", "")
                if url:
                    w = s.get("width", 0)
                    h = s.get("height", 0)
                    bitrate = s.get("videoBitrate", 0) or s.get("avgBitrate", 0)
                    label = f"{h}p" if h else codec
                    video_streams.append({
                        "url": url,
                        "codec": codec,
                        "width": w,
                        "height": h,
                        "bitrate": bitrate,
                        "label": f"{label} ({codec})",
                    })
        # Best quality as default
        if video_streams:
            # Sort by height descending, prefer h264 for compatibility
            sorted_streams = sorted(video_streams, key=lambda s: (s["height"], s["codec"] == "h264"), reverse=True)
            video_url = sorted_streams[0]["url"]
        elif not video_url:
            video_url = video.get("url", "")

    # Author
    user = note_data.get("user", {})
    author = user.get("nickname", "")
    avatar = user.get("avatar", "")

    # Stats
    interact = note_data.get("interactInfo", {})

    def safe_int(val):
        if not val or val == "":
            return 0
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0

    return {
        "title": title,
        "desc": desc,
        "tags": tags,
        "images": images,
        "video_url": video_url,
        "video_streams": video_streams,
        "author": author,
        "avatar": avatar,
        "likes": safe_int(interact.get("likedCount")),
        "collects": safe_int(interact.get("collectedCount")),
        "comments_count": safe_int(interact.get("commentCount")),
        "note_id": note_id,
        "type": note_type,
    }


def _cache_cleanup():
    """Evict expired or excess cache entries."""
    now = time.time()
    expired = [k for k, (_, _, ts) in _image_cache.items() if now - ts > _CACHE_TTL]
    for k in expired:
        del _image_cache[k]
    # If still over limit, evict oldest
    if len(_image_cache) > _CACHE_MAX:
        sorted_keys = sorted(_image_cache, key=lambda k: _image_cache[k][2])
        for k in sorted_keys[:len(_image_cache) - _CACHE_MAX]:
            del _image_cache[k]


def proxy_image(image_url: str, cookie: str = "") -> tuple[bytes, str]:
    """Fetch image through proxy with caching and content-type validation."""
    cache_key = md5(image_url.encode()).hexdigest()

    # Check cache
    if cache_key in _image_cache:
        data, ct, ts = _image_cache[cache_key]
        if time.time() - ts < _CACHE_TTL:
            return data, ct

    def do_fetch():
        resp = _http_pool.get(image_url)
        resp.raise_for_status()
        return resp

    resp = _retry(do_fetch)
    content_type = resp.headers.get("Content-Type", "image/jpeg")

    # Content-type validation: only allow image types
    if not content_type.startswith("image/"):
        # Force safe content type to prevent XSS
        content_type = "image/jpeg"

    data = resp.content

    # Cache it
    _image_cache[cache_key] = (data, content_type, time.time())
    if len(_image_cache) > _CACHE_MAX + 20:
        _cache_cleanup()

    return data, content_type


def proxy_video_stream(video_url: str, range_header: str = "", cookie: str = ""):
    """Stream video through proxy with Range request support for seeking."""
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Referer": "https://www.xiaohongshu.com/",
    }
    if range_header:
        headers["Range"] = range_header

    client = httpx.Client(follow_redirects=True, headers=headers, timeout=60)
    resp = client.send(
        client.build_request("GET", video_url),
        stream=True,
    )
    resp.raise_for_status()

    def generate():
        try:
            for chunk in resp.iter_bytes(chunk_size=65536):
                yield chunk
        finally:
            resp.close()
            client.close()

    return {
        "status_code": resp.status_code,
        "content_type": resp.headers.get("Content-Type", "video/mp4"),
        "content_length": resp.headers.get("Content-Length", ""),
        "content_range": resp.headers.get("Content-Range", ""),
        "accept_ranges": resp.headers.get("Accept-Ranges", "bytes"),
        "stream": generate(),
    }
