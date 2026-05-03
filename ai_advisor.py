import os
import json
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)


def _build_prompt(price: float, candles: list) -> str:
    candle_text = ""
    if candles:
        rows = candles[-10:]
        candle_text = "\n".join(
            f"  {c['time']} O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']}"
            for c in rows
        )
    return (
        f"You are a professional crypto trader analyzing ETH/USDT.\n"
        f"Current ETH price: ${price:.2f}\n"
        f"Last 10 one-minute candles (time, open, high, low, close):\n{candle_text}\n\n"
        f"Based on this price action, should I open a LONG or SHORT position for the next 1 hour?\n"
        f"Reply with ONLY one word: LONG or SHORT."
    )


def _parse_direction(text: str) -> str:
    t = text.strip().upper()
    if "LONG" in t:
        return "long"
    if "SHORT" in t:
        return "short"
    return "unknown"


def ask_chatgpt(prompt: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {"name": "ChatGPT", "direction": "unknown", "error": "API key not set", "raw": ""}
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
                "temperature": 0.2,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "ChatGPT", "direction": _parse_direction(raw), "raw": raw, "error": None}
        return {"name": "ChatGPT", "direction": "unknown", "raw": "", "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        logger.error(f"ChatGPT error: {e}")
        return {"name": "ChatGPT", "direction": "unknown", "raw": "", "error": str(e)}


def ask_gemini(prompt: str) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return {"name": "Gemini", "direction": "unknown", "error": "API key not set", "raw": ""}
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 10, "temperature": 0.2}},
            timeout=15,
        )
        if resp.status_code == 200:
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return {"name": "Gemini", "direction": _parse_direction(raw), "raw": raw, "error": None}
        return {"name": "Gemini", "direction": "unknown", "raw": "", "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return {"name": "Gemini", "direction": "unknown", "raw": "", "error": str(e)}


def ask_grok(prompt: str) -> dict:
    api_key = os.getenv("XAI_API_KEY", "")
    if not api_key:
        return {"name": "Grok", "direction": "unknown", "error": "API key not set", "raw": ""}
    try:
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "grok-3-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
                "temperature": 0.2,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "Grok", "direction": _parse_direction(raw), "raw": raw, "error": None}
        return {"name": "Grok", "direction": "unknown", "raw": "", "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        logger.error(f"Grok error: {e}")
        return {"name": "Grok", "direction": "unknown", "raw": "", "error": str(e)}


def ask_deepseek(prompt: str) -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"name": "DeepSeek", "direction": "unknown", "error": "API key not set", "raw": ""}
    try:
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
                "temperature": 0.2,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "DeepSeek", "direction": _parse_direction(raw), "raw": raw, "error": None}
        return {"name": "DeepSeek", "direction": "unknown", "raw": "", "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return {"name": "DeepSeek", "direction": "unknown", "raw": "", "error": str(e)}


def poll_all_ai(price: float, candles: list) -> dict:
    prompt = _build_prompt(price, candles)
    results = []

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(ask_chatgpt, prompt): "ChatGPT",
            ex.submit(ask_gemini, prompt): "Gemini",
            ex.submit(ask_grok, prompt): "Grok",
            ex.submit(ask_deepseek, prompt): "DeepSeek",
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                name = futures[future]
                results.append({"name": name, "direction": "unknown", "raw": "", "error": str(e)})

    longs = sum(1 for r in results if r["direction"] == "long")
    shorts = sum(1 for r in results if r["direction"] == "short")

    if longs > shorts:
        consensus = "long"
    elif shorts > longs:
        consensus = "short"
    else:
        consensus = "none"

    return {
        "results": results,
        "consensus": consensus,
        "long_votes": longs,
        "short_votes": shorts,
        "price": price,
        "timestamp": datetime.utcnow().isoformat(),
    }
