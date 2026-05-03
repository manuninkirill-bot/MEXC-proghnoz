import os
import json
import logging
import requests
from datetime import datetime
import concurrent.futures

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


def _friendly_error(raw_error: str) -> str:
    e = raw_error.lower()
    if "api key not set" in e:
        return "API-ключ не задан"
    if "429" in raw_error or "quota" in e or "rate_limit" in e:
        return "Квота исчерпана"
    if "402" in raw_error or "insufficient" in e or "balance" in e:
        return "Нет средств на счёте"
    if "403" in raw_error or "permission" in e or "credits" in e or "license" in e:
        return "Нет кредитов на аккаунте"
    if "401" in raw_error or "unauthorized" in e or "incorrect api key" in e:
        return "Неверный API-ключ"
    if "timed out" in e or "timeout" in e:
        return "Таймаут"
    if "connection" in e:
        return "Ошибка соединения"
    return "Ошибка"


def ask_chatgpt(prompt: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {"name": "ChatGPT", "direction": "unknown", "error": "API-ключ не задан", "raw": ""}
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
            timeout=20,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "ChatGPT", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "ChatGPT", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"ChatGPT error: {e}")
        return {"name": "ChatGPT", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def ask_groq(prompt: str) -> dict:
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return {"name": "Groq", "direction": "unknown", "error": "API-ключ не задан", "raw": ""}
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
                "temperature": 0.2,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "Groq", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "Groq", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return {"name": "Groq", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def ask_gemini(prompt: str) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return {"name": "Gemini", "direction": "unknown", "error": "API-ключ не задан", "raw": ""}
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": 200,
                    "temperature": 0.2,
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            },
            timeout=30,
        )
        if resp.status_code == 200:
            parts = resp.json()["candidates"][0]["content"].get("parts", [])
            raw = parts[0]["text"] if parts else ""
            if not raw:
                return {"name": "Gemini", "direction": "unknown", "raw": "", "error": "Пустой ответ"}
            return {"name": "Gemini", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "Gemini", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return {"name": "Gemini", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def ask_grok(prompt: str) -> dict:
    api_key = os.getenv("XAI_API_KEY", "")
    if not api_key:
        return {"name": "Grok", "direction": "unknown", "error": "API-ключ не задан", "raw": ""}
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
            timeout=20,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "Grok", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "Grok", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"Grok error: {e}")
        return {"name": "Grok", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def ask_deepseek(prompt: str) -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"name": "DeepSeek", "direction": "unknown", "error": "API-ключ не задан", "raw": ""}
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
            timeout=20,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "DeepSeek", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "DeepSeek", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return {"name": "DeepSeek", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def ask_openrouter(prompt: str) -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return {"name": "OpenRouter", "direction": "unknown", "error": "API-ключ не задан", "raw": ""}
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "deepseek/deepseek-chat-v3.1:free",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
                "temperature": 0.2,
            },
            timeout=25,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "OpenRouter", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "OpenRouter", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        return {"name": "OpenRouter", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def ask_mistral(prompt: str) -> dict:
    api_key = os.getenv("MISTRAL_API_KEY", "")
    if not api_key:
        return {"name": "Mistral", "direction": "unknown", "error": "API-ключ не задан", "raw": ""}
    try:
        resp = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
                "temperature": 0.2,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "Mistral", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "Mistral", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"Mistral error: {e}")
        return {"name": "Mistral", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def poll_all_ai(price: float, candles: list) -> dict:
    prompt = _build_prompt(price, candles)
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futures = {
            ex.submit(ask_chatgpt, prompt): "ChatGPT",
            ex.submit(ask_gemini, prompt): "Gemini",
            ex.submit(ask_grok, prompt): "Grok",
            ex.submit(ask_deepseek, prompt): "DeepSeek",
            ex.submit(ask_groq, prompt): "Groq",
            ex.submit(ask_openrouter, prompt): "OpenRouter",
            ex.submit(ask_mistral, prompt): "Mistral",
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
