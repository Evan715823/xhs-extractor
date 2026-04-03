# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

XHS Extractor (小红书内容提取器) — a self-hosted Flask web app that extracts original-quality images and full text content from Xiaohongshu (Little Red Book) note URLs, with optional LLM-powered summarization.

## Running Locally

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in LLM_API_KEY
python app.py           # serves on http://localhost:5000
```

Docker: `docker compose up -d` (reads `.env` file).

Set `FLASK_DEBUG=true` in `.env` for auto-reload during development.

## Architecture

**Backend (Python/Flask):**
- `app.py` — Flask routes: `/api/extract` (POST), `/api/proxy-image` (GET), `/api/download-all` (POST), `/api/summarize` (POST), and `/` (serves the SPA)
- `scraper.py` — Core scraping logic. Resolves short URLs (`xhslink.com`), fetches note pages, extracts data via two fallback strategies: `__INITIAL_STATE__` JSON parsing, then Open Graph meta tags. Also handles image proxying to bypass hotlink protection.
- `llm_service.py` — LLM abstraction supporting three providers via `LLM_PROVIDER` env var: `grok` (default, uses xAI's OpenAI-compatible API), `openai`, and `anthropic`. Each uses lazy imports.

**Frontend (vanilla JS, single-page):**
- `templates/index.html` — Full page with inline SVG illustrations, pixel-art theme
- `static/app.js` — All client logic: extract flow, result rendering, image lightbox, clipboard copy, ZIP download, AI summary
- `static/style.css` — Styling

**Key design decisions:**
- Images are proxied through `/api/proxy-image` to bypass XHS hotlink protection; `fileId` + unsigned CDN (`sns-img-bd.xhscdn.com`) is preferred for watermark-free originals
- XHS anti-scraping tokens (`xsec_token`, `xsec_source`) are preserved from resolved URLs
- The app uses `httpx` (not `requests`) for HTTP with redirect following
- No database — everything is stateless and extracted on-the-fly

## Environment Variables

Required: `LLM_API_KEY` (for AI summarization feature).
Optional: `LLM_PROVIDER` (grok/openai/anthropic), `LLM_MODEL`, `LLM_BASE_URL`, `XHS_COOKIE` (for login-gated notes).

## Language

The UI and error messages are in Chinese (zh-CN). Code comments and docstrings are a mix of Chinese and English.
