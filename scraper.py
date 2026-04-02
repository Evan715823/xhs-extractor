"""
小红书笔记内容抓取器
Extracts images, text, and metadata from Xiaohongshu note URLs.
"""

import json
import re

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


def _build_headers(cookie: str = "", referer: str = "https://www.xiaohongshu.com/") -> dict:
    headers = HEADERS.copy()
    headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    return headers


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
    with httpx.Client(follow_redirects=True, headers=headers, timeout=15) as client:
        resp = client.get(url)
        return str(resp.url)


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
    # Remove query params that control image size/compression
    if "?" in url:
        base = url.split("?")[0]
    else:
        base = url
    # Remove XHS image processing suffix (e.g. !h5_1080jpg) which adds watermark
    if "!" in base:
        base = base.split("!")[0]
    if base.startswith("http://"):
        base = "https://" + base[7:]
    if not base.startswith("http"):
        base = "https://" + base
    return base


# CDN host that serves original images without watermark or signed URLs
_ORIGINAL_CDN = "https://sns-img-bd.xhscdn.com"


def _fix_json_text(text: str) -> str:
    """Fix XHS's non-standard JSON (undefined values, etc.)."""
    text = text.replace("undefined", "null")
    return text


def _parse_initial_state(soup: BeautifulSoup, note_id: str) -> dict | None:
    """Try to extract note data from __INITIAL_STATE__ script tag."""
    for script in soup.find_all("script"):
        text = script.string or ""
        if "window.__INITIAL_STATE__" in text:
            json_str = text.split("window.__INITIAL_STATE__=", 1)[1]
            json_str = _fix_json_text(json_str)
            try:
                state = json.loads(json_str)
            except json.JSONDecodeError:
                return None

            # New structure: noteData.data.noteData
            note_data = (
                state.get("noteData", {})
                .get("data", {})
                .get("noteData")
            )
            if note_data:
                return note_data

            # Legacy structure: note.noteDetailMap
            note_detail_map = state.get("note", {}).get("noteDetailMap", {})
            note_data = note_detail_map.get(note_id, {}).get("note")
            if not note_data:
                for key, val in note_detail_map.items():
                    note_data = val.get("note")
                    if note_data:
                        break

            return note_data
    return None


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

    # Try to find more images from JSON-LD
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
    # Extract URL from share text
    url = _extract_url_from_text(url)

    # Resolve short links
    resolved_url = _resolve_short_url(url, cookie)
    note_id = _extract_note_id(resolved_url)
    if not note_id:
        raise ValueError(f"无法从 URL 中提取笔记ID: {resolved_url}")

    # Preserve xsec_token and xsec_source from resolved URL (required by XHS anti-scraping)
    xsec_token = _extract_xsec_token(resolved_url)
    xsec_source_match = re.search(r'[?&]xsec_source=([^&]+)', resolved_url)
    xsec_source = xsec_source_match.group(1) if xsec_source_match else ""

    # Fetch the page — use resolved URL with tokens if available
    page_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    params = {}
    if xsec_token:
        params["xsec_token"] = xsec_token
    if xsec_source:
        params["xsec_source"] = xsec_source
    headers = _build_headers(cookie)

    with httpx.Client(follow_redirects=True, headers=headers, timeout=20) as client:
        resp = client.get(page_url, params=params)
        resp.raise_for_status()

    html = resp.text
    soup = BeautifulSoup(html, "lxml")

    # Strategy 1: Parse __INITIAL_STATE__
    note_data = _parse_initial_state(soup, note_id)

    if note_data:
        return _build_result_from_state(note_data, note_id)

    # Strategy 2: Parse meta tags (works without cookie)
    meta_data = _parse_meta_tags(soup)
    if meta_data:
        return {
            "title": meta_data["title"],
            "desc": meta_data["desc"],
            "tags": [],
            "images": meta_data["images"],
            "video_url": "",
            "author": meta_data["author"],
            "avatar": "",
            "likes": 0,
            "collects": 0,
            "comments": 0,
            "note_id": note_id,
            "type": "normal",
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
            # Use unsigned CDN with fileId for watermark-free original
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

    # Video
    video = note_data.get("video", {})
    video_url = ""
    if video:
        media = video.get("media", {})
        stream = media.get("stream", {})
        for quality in ["h265", "h264", "av1"]:
            streams = stream.get(quality, [])
            if streams:
                video_url = streams[0].get("masterUrl", "")
                break
        if not video_url:
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
        "author": author,
        "avatar": avatar,
        "likes": safe_int(interact.get("likedCount")),
        "collects": safe_int(interact.get("collectedCount")),
        "comments": safe_int(interact.get("commentCount")),
        "note_id": note_id,
        "type": note_type,
    }


def proxy_image(image_url: str, cookie: str = "") -> tuple[bytes, str]:
    """Fetch image through proxy to bypass hotlink protection."""
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Referer": "https://www.xiaohongshu.com/",
    }
    with httpx.Client(follow_redirects=True, headers=headers, timeout=30) as client:
        resp = client.get(image_url)
        resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "image/jpeg")
    return resp.content, content_type
