"""
小红书笔记内容抓取器
Extracts images, text, and metadata from Xiaohongshu note URLs.
"""

import json
import re
from urllib.parse import urlparse, urlencode

import httpx
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.xiaohongshu.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _build_headers(cookie: str = "") -> dict:
    headers = HEADERS.copy()
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _resolve_short_url(url: str, cookie: str = "") -> str:
    """Resolve xhslink.com short URLs to full xiaohongshu.com URLs."""
    if "xhslink.com" not in url:
        return url
    with httpx.Client(follow_redirects=True, headers=_build_headers(cookie)) as client:
        resp = client.get(url)
        return str(resp.url)


def _extract_note_id(url: str) -> str | None:
    """Extract note_id from various XHS URL formats."""
    patterns = [
        r"/explore/([a-f0-9]{24})",
        r"/discovery/item/([a-f0-9]{24})",
        r"/note/([a-f0-9]{24})",
        r"noteId=([a-f0-9]{24})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _clean_image_url(url: str) -> str:
    """Remove image processing parameters to get original quality."""
    if "?" in url:
        base = url.split("?")[0]
    else:
        base = url
    # Ensure https
    if base.startswith("http://"):
        base = "https://" + base[7:]
    return base


def _fix_json_text(text: str) -> str:
    """Fix XHS's non-standard JSON (undefined values, etc.)."""
    text = text.replace("undefined", "null")
    return text


def extract_note(url: str, cookie: str = "") -> dict:
    """
    Extract content from a Xiaohongshu note URL.

    Returns:
        {
            "title": str,
            "desc": str,
            "tags": [str],
            "images": [str],      # original quality image URLs
            "author": str,
            "avatar": str,
            "likes": int,
            "collects": int,
            "comments": int,
            "note_id": str,
            "type": "normal" | "video",
        }
    """
    # Resolve short links
    resolved_url = _resolve_short_url(url, cookie)
    note_id = _extract_note_id(resolved_url)
    if not note_id:
        raise ValueError(f"无法从 URL 中提取笔记ID: {url}")

    # Fetch the page
    page_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    headers = _build_headers(cookie)

    with httpx.Client(follow_redirects=True, headers=headers, timeout=15) as client:
        resp = client.get(page_url)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # Extract __INITIAL_STATE__ JSON from script tag
    initial_state = None
    for script in soup.find_all("script"):
        text = script.string or ""
        if "window.__INITIAL_STATE__" in text:
            # Format: window.__INITIAL_STATE__=JSON
            json_str = text.split("window.__INITIAL_STATE__=", 1)[1]
            json_str = _fix_json_text(json_str)
            initial_state = json.loads(json_str)
            break

    if not initial_state:
        raise ValueError("无法解析页面数据，可能需要登录Cookie或页面结构已变更")

    # Navigate to note data
    note_data = (
        initial_state.get("note", {})
        .get("noteDetailMap", {})
        .get(note_id, {})
        .get("note", {})
    )

    if not note_data:
        raise ValueError(f"未找到笔记数据 (note_id: {note_id})，请确认链接有效或尝试提供Cookie")

    # Extract fields
    title = note_data.get("title", "")
    desc = note_data.get("desc", "")
    note_type = note_data.get("type", "normal")

    # Tags from desc (hashtag format: #tag[topic]#)
    tag_list = note_data.get("tagList", [])
    tags = [t.get("name", "") for t in tag_list if t.get("name")]
    # Also extract inline hashtags from desc
    inline_tags = re.findall(r"#([^#\[\]]+?)(?:\[话题\])?#", desc)
    for t in inline_tags:
        t = t.strip()
        if t and t not in tags:
            tags.append(t)

    # Images
    image_list = note_data.get("imageList", [])
    images = []
    for img in image_list:
        # Try to get the highest quality URL
        info_list = img.get("infoList", [])
        if info_list:
            # Sort by width descending, pick largest
            info_list_sorted = sorted(info_list, key=lambda x: x.get("width", 0), reverse=True)
            best = info_list_sorted[0].get("url", "")
        else:
            best = img.get("urlDefault", "") or img.get("url", "")
        if best:
            images.append(_clean_image_url(best))

    # Video (if video note)
    video = note_data.get("video", {})
    video_url = ""
    if video:
        media = video.get("media", {})
        stream = media.get("stream", {})
        # Get highest quality video stream
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

    # Interaction info
    interact = note_data.get("interactInfo", {})
    likes = int(interact.get("likedCount", "0") if interact.get("likedCount", "0") != "" else "0")
    collects = int(interact.get("collectedCount", "0") if interact.get("collectedCount", "0") != "" else "0")
    comments = int(interact.get("commentCount", "0") if interact.get("commentCount", "0") != "" else "0")

    return {
        "title": title,
        "desc": desc,
        "tags": tags,
        "images": images,
        "video_url": video_url,
        "author": author,
        "avatar": avatar,
        "likes": likes,
        "collects": collects,
        "comments": comments,
        "note_id": note_id,
        "type": note_type,
    }


def proxy_image(image_url: str, cookie: str = "") -> tuple[bytes, str]:
    """
    Fetch image through proxy to bypass hotlink protection.
    Returns (image_bytes, content_type).
    """
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Referer": "https://www.xiaohongshu.com/",
    }
    with httpx.Client(follow_redirects=True, headers=headers, timeout=30) as client:
        resp = client.get(image_url)
        resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "image/jpeg")
    return resp.content, content_type
