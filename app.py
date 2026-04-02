"""
XHS Extractor - Flask API
小红书内容提取工具后端
"""

import io
import os
import zipfile

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file

from scraper import extract_note, proxy_image
from llm_service import summarize

load_dotenv()

app = Flask(__name__)

XHS_COOKIE = os.getenv("XHS_COOKIE", "")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/extract", methods=["POST"])
def api_extract():
    """Extract images and text from a Xiaohongshu note URL."""
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "请输入小红书笔记链接"}), 400

    # Basic validation: must contain XHS link somewhere in the text
    if not any(domain in url for domain in ["xiaohongshu.com", "xhslink.com", "xhscdn.com"]):
        return jsonify({"error": "未检测到小红书链接，请粘贴完整的分享文本"}), 400

    try:
        result = extract_note(url, cookie=XHS_COOKIE)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"提取失败: {str(e)}"}), 500


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


@app.route("/api/download-all", methods=["POST"])
def api_download_all():
    """Download all images as a ZIP file."""
    data = request.get_json()
    images = data.get("images", [])
    title = data.get("title", "xhs_images")

    if not images:
        return jsonify({"error": "没有可下载的图片"}), 400

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
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
                continue

    zip_buffer.seek(0)
    # Sanitize filename
    safe_title = "".join(c for c in title if c.isalnum() or c in " _-")[:50] or "xhs_images"
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{safe_title}.zip",
    )


@app.route("/api/summarize", methods=["POST"])
def api_summarize():
    """Summarize note content using LLM API."""
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
