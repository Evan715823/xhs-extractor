# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

XHS Extractor is a Flask-based web app that scrapes Xiaohongshu (小红书) notes to extract original-quality images, text, and tags, with optional AI summarization.

## Running the App

```bash
# Local development
pip install -r requirements.txt
cp .env.example .env   # fill in LLM_API_KEY at minimum
python app.py          # http://localhost:5000

# Docker
docker compose up -d --build
```

No test suite or lint commands exist in this project.

## Environment Variables (.env)

| Variable | Default | Notes |
|---|---|---|
| `LLM_API_KEY` | — | Required |
| `LLM_PROVIDER` | `grok` | `grok`, `openai`, or `anthropic` |
| `LLM_MODEL` | `grok-3` | Also supports `grok-3-mini`, `gpt-4o`, `claude-sonnet-4-6` |
| `LLM_BASE_URL` | — | Optional custom API endpoint |
| `XHS_COOKIE` | — | Optional; needed for login-protected notes |
| `FLASK_PORT` | `5000` | Cloud deployments override with `PORT` |

## Architecture

```
app.py          Flask routes and request handling
scraper.py      Core XHS scraping logic (URL parsing → page fetch → data extraction)
llm_service.py  Provider-agnostic LLM wrapper (Grok/OpenAI/Anthropic)
static/app.js   Frontend: form handling, image gallery, lightbox, downloads
templates/index.html  Single-page app shell
```

### API Endpoints

- `POST /api/extract` — main extraction; input: `{url: "<share text or URL>"}`, output: note metadata + image URLs
- `GET /api/proxy-image?url=...` — proxies XHS images (bypasses hotlink protection with correct Referer header)
- `POST /api/download-all` — streams ZIP of all images
- `POST /api/summarize` — sends title/desc/tags to configured LLM

### Scraper Fallback Chain (`scraper.py`)

1. Parse `__INITIAL_STATE__` JSON embedded in page HTML (primary path)
2. Extract OpenGraph `<meta>` tags (fallback)
3. Parse JSON-LD structured data (second fallback)

The scraper uses iPhone Safari User-Agent to get mobile-optimized responses. It fixes malformed XHS JSON by replacing literal `undefined` with `null` before parsing.

### LLM Integration (`llm_service.py`)

All three providers use an OpenAI-compatible client. Grok and OpenAI use `openai.OpenAI` with different `base_url`; Anthropic uses `anthropic.Anthropic`. The system prompt is in Chinese and requests structured content analysis.
