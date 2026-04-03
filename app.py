"""
XHS Extractor - Flask API
小红书内容提取工具后端
"""

import io
import os
import time
import zipfile
from collections import defaultdict

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, send_file

from scraper import extract_note, proxy_image, proxy_video_stream
from llm_service import summarize

load_dotenv()

app = Flask(__name__)

XHS_COOKIE = os.getenv("XHS_COOKIE", "")

# --- Simple in-memory rate limiter ---
_rate_store: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 15       # requests per window
_RATE_WINDOW = 60      # seconds


def _check_rate_limit() -> bool:
    """Returns True if request should be blocked."""
    ip = request.remote_addr or "unknown"
    now = time.time()
    timestamps = _rate_store[ip]
    # Purge old entries
    _rate_store[ip] = [t for t in timestamps if now - t < _RATE_WINDOW]
    if len(_rate_store[ip]) >= _RATE_LIMIT:
        return True
    _rate_store[ip].append(now)
    return False


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/extract", methods=["POST"])
def api_extract():
    """Extract images and text from a Xiaohongshu note URL."""
    if _check_rate_limit():
        return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "请输入小红书笔记链接"}), 400

    if len(url) > 2048:
        return jsonify({"error": "输入文本过长"}), 400

    if not any(domain in url for domain in ["xiaohongshu.com", "xhslink.com", "xhscdn.com"]):
        return jsonify({"error": "未检测到小红书链接，请粘贴完整的分享文本"}), 400

    try:
        result = extract_note(url, cookie=XHS_COOKIE)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"提取失败: {str(e)}"}), 500


@app.route("/api/batch-extract", methods=["POST"])
def api_batch_extract():
    """Extract multiple notes from a list of URLs."""
    if _check_rate_limit():
        return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    data = request.get_json()
    urls = data.get("urls", [])

    if not urls:
        return jsonify({"error": "请提供至少一个链接"}), 400

    if len(urls) > 10:
        return jsonify({"error": "一次最多提取10个链接"}), 400

    results = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            result = extract_note(url, cookie=XHS_COOKIE)
            results.append({"success": True, "data": result})
        except Exception as e:
            results.append({"success": False, "error": str(e), "url": url})

    return jsonify({"results": results})


@app.route("/api/proxy-image")
def api_proxy_image():
    """Proxy XHS images to bypass hotlink protection."""
    image_url = request.args.get("url", "")
    if not image_url:
        return jsonify({"error": "Missing image URL"}), 400

    try:
        image_bytes, content_type = proxy_image(image_url, cookie=XHS_COOKIE)
        return send_file(
            io.BytesIO(image_bytes),
            mimetype=content_type,
            max_age=86400,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/proxy-video")
def api_proxy_video():
    """Proxy XHS video with Range support for seeking."""
    video_url = request.args.get("url", "")
    if not video_url:
        return jsonify({"error": "Missing video URL"}), 400

    try:
        range_header = request.headers.get("Range", "")
        result = proxy_video_stream(video_url, range_header=range_header, cookie=XHS_COOKIE)

        resp_headers = {
            "Content-Type": result["content_type"],
            "Accept-Ranges": result["accept_ranges"],
        }
        if result["content_length"]:
            resp_headers["Content-Length"] = result["content_length"]
        if result["content_range"]:
            resp_headers["Content-Range"] = result["content_range"]

        status = result["status_code"]
        return Response(result["stream"], status=status, headers=resp_headers)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download-all", methods=["POST"])
def api_download_all():
    """Download all images as a ZIP file."""
    data = request.get_json()
    images = data.get("images", [])
    title = data.get("title", "xhs_images")

    if not images:
        return jsonify({"error": "没有可下载的图片"}), 400

    if len(images) > 50:
        return jsonify({"error": "一次最多下载50张图片"}), 400

    zip_buffer = io.BytesIO()
    failed = 0
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, img_url in enumerate(images):
            try:
                img_bytes, content_type = proxy_image(img_url, cookie=XHS_COOKIE)
                ext = "jpg"
                if "png" in content_type:
                    ext = "png"
                elif "webp" in content_type:
                    ext = "webp"
                zf.writestr(f"{i + 1:02d}.{ext}", img_bytes)
            except Exception:
                failed += 1
                continue

    zip_buffer.seek(0)
    safe_title = "".join(c for c in title if c.isalnum() or c in " _-")[:50] or "xhs_images"

    resp = send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{safe_title}.zip",
    )
    if failed:
        resp.headers["X-Failed-Count"] = str(failed)
    return resp


@app.route("/api/summarize", methods=["POST"])
def api_summarize():
    """Summarize note content using LLM API."""
    if _check_rate_limit():
        return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    data = request.get_json()
    title = data.get("title", "")
    desc = data.get("desc", "")
    tags = data.get("tags", [])

    if not desc and not title:
        return jsonify({"error": "没有可总结的内容"}), 400

    try:
        summary = summarize(title, desc, tags)
        return jsonify({"summary": summary})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"总结失败: {str(e)}"}), 500


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("FLASK_PORT", "5000")))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)
