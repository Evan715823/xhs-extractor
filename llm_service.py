"""
LLM API 调用封装
Supports Grok (xAI), OpenAI, and Anthropic APIs for content summarization.
"""

import os

SYSTEM_PROMPT = """你是一个专业的内容分析助手。请对以下小红书笔记内容进行简洁有深度的总结分析。

请按以下格式输出：
📌 核心内容：用1-2句话概括笔记的主要内容
🔑 关键要点：提取3-5个关键信息点
🏷️ 话题分析：分析标签所涉及的领域和受众
💡 内容价值：简评该内容的实用性或趣味性"""

# Grok API is OpenAI-compatible, just with a different base URL
GROK_BASE_URL = "https://api.x.ai/v1"


def summarize(title: str, desc: str, tags: list[str]) -> str:
    """Call configured LLM API to summarize note content."""
    provider = os.getenv("LLM_PROVIDER", "grok").lower()
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "grok-3")
    base_url = os.getenv("LLM_BASE_URL", "")

    if not api_key:
        raise ValueError("未配置 LLM_API_KEY，请在 .env 中设置")

    user_message = f"标题：{title}\n\n正文：{desc}\n\n标签：{', '.join(tags)}"

    if provider == "anthropic":
        return _call_anthropic(api_key, model, base_url, user_message)
    elif provider == "grok":
        # Grok uses OpenAI-compatible API with xAI base URL
        grok_url = base_url or GROK_BASE_URL
        return _call_openai(api_key, model, grok_url, user_message)
    else:
        return _call_openai(api_key, model, base_url, user_message)


def _call_openai(api_key: str, model: str, base_url: str, user_message: str) -> str:
    from openai import OpenAI

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url

    client = OpenAI(**kwargs)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_tokens=1024,
        temperature=0.7,
    )
    return response.choices[0].message.content


def _call_anthropic(api_key: str, model: str, base_url: str, user_message: str) -> str:
    from anthropic import Anthropic

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url

    client = Anthropic(**kwargs)
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_message},
        ],
    )
    return response.content[0].text
