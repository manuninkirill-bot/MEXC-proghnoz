import os
import json
import logging
import requests
from datetime import datetime
import concurrent.futures

logger = logging.getLogger(__name__)


def _pct(a: float, b: float) -> float:
    if not b:
        return 0.0
    return (a - b) / b * 100.0


def _stats(candles_1m: list) -> dict:
    """Compute basic technical statistics from 1m candles."""
    if not candles_1m:
        return {}
    closes = [float(c["close"]) for c in candles_1m]
    highs  = [float(c["high"])  for c in candles_1m]
    lows   = [float(c["low"])   for c in candles_1m]
    vols   = [float(c.get("volume", 0)) for c in candles_1m]
    cur = closes[-1]

    def back(n):
        return closes[-n] if len(closes) >= n else closes[0]

    sma5  = sum(closes[-5:])  / min(5, len(closes))
    sma20 = sum(closes[-20:]) / min(20, len(closes))
    hi30  = max(highs[-30:])
    lo30  = min(lows[-30:])
    rng   = hi30 - lo30
    avg_vol = sum(vols[-30:]) / max(1, len(vols[-30:]))
    cur_vol = vols[-1] if vols else 0
    # Простой RSI-14
    gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
    losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
    g = sum(gains[-14:]) / 14 if len(gains) >= 14 else (sum(gains)/max(1,len(gains)))
    l = sum(losses[-14:]) / 14 if len(losses) >= 14 else (sum(losses)/max(1,len(losses)))
    rsi = 100 - 100 / (1 + g/l) if l > 0 else 100.0
    # Волатильность — стандартное отклонение последних 20 закрытий
    last20 = closes[-20:]
    mean20 = sum(last20) / len(last20)
    variance = sum((x - mean20) ** 2 for x in last20) / len(last20)
    vol_std = variance ** 0.5
    if sma5 > sma20 * 1.0005:
        trend = "BULLISH (SMA5>SMA20)"
    elif sma5 < sma20 * 0.9995:
        trend = "BEARISH (SMA5<SMA20)"
    else:
        trend = "SIDEWAYS (SMA5≈SMA20)"
    return {
        "current": cur,
        "ago_1m":  back(2),
        "ago_5m":  back(6),
        "ago_15m": back(16),
        "ago_30m": back(31) if len(closes) >= 31 else closes[0],
        "high_30m": hi30,
        "low_30m": lo30,
        "range_30m": rng,
        "rsi14": rsi,
        "trend": trend,
        "volatility_std": vol_std,
        "avg_vol_30m": avg_vol,
        "cur_vol": cur_vol,
        "sma5": sma5,
        "sma20": sma20,
    }


def _build_prompt(price: float, candles_1m: list, candles_5m: list | None = None) -> str:
    candles_5m = candles_5m or []
    s = _stats(candles_1m)

    # Список свечей 1m (последние 30)
    rows_1m = candles_1m[-30:] if candles_1m else []
    text_1m = "\n".join(
        f"  {c['time']} O:{c['open']:.2f} H:{c['high']:.2f} L:{c['low']:.2f} C:{c['close']:.2f} V:{float(c.get('volume',0)):.2f}"
        for c in rows_1m
    ) or "  (нет данных)"

    rows_5m = candles_5m[-12:] if candles_5m else []
    text_5m = "\n".join(
        f"  {c['time']} O:{c['open']:.2f} H:{c['high']:.2f} L:{c['low']:.2f} C:{c['close']:.2f} V:{float(c.get('volume',0)):.2f}"
        for c in rows_5m
    ) or "  (нет данных)"

    if s:
        snap = (
            f"Current price:  ${s['current']:.2f}\n"
            f"1m  ago: ${s['ago_1m']:.2f}  ({_pct(s['current'], s['ago_1m']):+.3f}%)\n"
            f"5m  ago: ${s['ago_5m']:.2f}  ({_pct(s['current'], s['ago_5m']):+.3f}%)\n"
            f"15m ago: ${s['ago_15m']:.2f} ({_pct(s['current'], s['ago_15m']):+.3f}%)\n"
            f"30m ago: ${s['ago_30m']:.2f} ({_pct(s['current'], s['ago_30m']):+.3f}%)\n"
        )
        stats_block = (
            f"High (30m): ${s['high_30m']:.2f}\n"
            f"Low  (30m): ${s['low_30m']:.2f}\n"
            f"Range (30m): ${s['range_30m']:.2f}  ({_pct(s['high_30m'], s['low_30m']):+.2f}%)\n"
            f"RSI(14): {s['rsi14']:.1f}  (oversold<30, overbought>70)\n"
            f"Trend:   {s['trend']}\n"
            f"SMA5:    ${s['sma5']:.2f}\n"
            f"SMA20:   ${s['sma20']:.2f}\n"
            f"Volatility (σ20): ${s['volatility_std']:.3f}\n"
            f"Avg volume (30m): {s['avg_vol_30m']:.2f} ETH\n"
            f"Current candle volume: {s['cur_vol']:.2f} ETH\n"
        )
    else:
        snap = f"Current price: ${price:.2f}\n"
        stats_block = "(no statistics available)\n"

    return (
        f"You are a professional crypto trader analyzing ETH/USDT perpetual futures on MEXC.\n"
        f"Your task: predict the SHORT-TERM (next 10 minutes) price direction.\n\n"
        f"=== MARKET SNAPSHOT ===\n{snap}\n"
        f"=== TECHNICAL STATISTICS ===\n{stats_block}\n"
        f"=== LAST 30 ONE-MINUTE CANDLES (oldest → newest) ===\n{text_1m}\n\n"
        f"=== LAST 12 FIVE-MINUTE CANDLES (oldest → newest, 1h history) ===\n{text_5m}\n\n"
        f"=== ANALYSIS GUIDE ===\n"
        f"- Look for momentum: are recent closes rising or falling?\n"
        f"- Watch volume: rising volume confirms a move; falling volume = weak move.\n"
        f"- RSI extremes (>70 or <30) often precede reversals.\n"
        f"- Trend direction (SMA5 vs SMA20) suggests dominant bias.\n"
        f"- Price near 30m High = resistance; near 30m Low = support.\n\n"
        f"=== DECISION ===\n"
        f"Will ETH price go UP or DOWN over the NEXT 10 MINUTES?\n"
        f"If UP   → reply LONG.\n"
        f"If DOWN → reply SHORT.\n"
        f"Reply with EXACTLY ONE WORD: LONG or SHORT. No explanation, no punctuation."
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


def ask_chatgpt(prompt: str, max_tokens: int = 10) -> dict:
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
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "ChatGPT", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "ChatGPT", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"ChatGPT error: {e}")
        return {"name": "ChatGPT", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def ask_groq(prompt: str, max_tokens: int = 10) -> dict:
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
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "Groq", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "Groq", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return {"name": "Groq", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def ask_gemini(prompt: str, max_tokens: int = 200) -> dict:
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
                    "maxOutputTokens": max_tokens,
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


def ask_grok(prompt: str, max_tokens: int = 10) -> dict:
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
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "Grok", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "Grok", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"Grok error: {e}")
        return {"name": "Grok", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def ask_deepseek(prompt: str, max_tokens: int = 10) -> dict:
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
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "DeepSeek", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "DeepSeek", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return {"name": "DeepSeek", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def ask_openrouter(prompt: str, max_tokens: int = 10) -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return {"name": "OpenRouter", "direction": "unknown", "error": "API-ключ не задан", "raw": ""}
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "google/gemma-4-31b-it:free",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "OpenRouter", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "OpenRouter", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        return {"name": "OpenRouter", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def ask_mistral(prompt: str, max_tokens: int = 10) -> dict:
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
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            return {"name": "Mistral", "direction": _parse_direction(raw), "raw": raw, "error": None}
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return {"name": "Mistral", "direction": "unknown", "raw": "", "error": _friendly_error(err)}
    except Exception as e:
        logger.error(f"Mistral error: {e}")
        return {"name": "Mistral", "direction": "unknown", "raw": "", "error": _friendly_error(str(e))}


def _parse_direction_and_reason(text) -> tuple[str, str]:
    """Извлекает направление (long/short/unknown) и аргумент (короткий текст) из ответа AI."""
    if not text or not isinstance(text, str):
        return "unknown", ""
    raw = text.strip()
    upper = raw.upper()
    direction = "unknown"
    if "LONG" in upper and "SHORT" not in upper:
        direction = "long"
    elif "SHORT" in upper and "LONG" not in upper:
        direction = "short"
    elif "LONG" in upper and "SHORT" in upper:
        direction = "long" if upper.find("LONG") < upper.find("SHORT") else "short"
    # Удаляем слово LONG/SHORT и двоеточие/тире, чтобы остался только аргумент
    reason = raw
    for token in ("LONG:", "SHORT:", "LONG —", "SHORT —", "LONG -", "SHORT -", "LONG.", "SHORT.", "LONG", "SHORT"):
        for variant in (token, token.lower(), token.title()):
            if variant in reason:
                reason = reason.replace(variant, "", 1)
                break
    reason = reason.strip(" \t\n\r:—-.,").strip()
    if len(reason) > 220:
        reason = reason[:217] + "..."
    return direction, reason


def _build_council_prompt_round1(price: float, candles_1m: list, candles_5m: list | None,
                                  question: str, last_trade_analysis: str | None = None) -> str:
    base = _build_prompt(price, candles_1m, candles_5m)
    cut = base.split("=== DECISION ===")[0]
    analysis_block = ""
    if last_trade_analysis:
        analysis_block = (
            "=== PREVIOUS TRADE ANALYSIS (use this as context) ===\n"
            + last_trade_analysis + "\n\n"
        )
    return (
        cut
        + analysis_block
        + "=== COUNCIL QUESTION ===\n"
        + question + "\n\n"
        + "=== ANSWER FORMAT ===\n"
        + "Reply on ONE line in this EXACT format:\n"
        + "LONG: <one short sentence why> \n"
        + "OR\n"
        + "SHORT: <one short sentence why>\n"
        + "Keep the reasoning under 25 words. No markdown, no extra lines."
    )


def _build_council_prompt_round2(price: float, candles_1m: list, candles_5m: list | None,
                                  question: str, peer_opinions: list) -> str:
    base = _build_prompt(price, candles_1m, candles_5m)
    cut = base.split("=== DECISION ===")[0]
    peers_text = "\n".join(
        f"  • {p['name']}: {p['direction'].upper()} — {p['reason'] or '(без аргумента)'}"
        for p in peer_opinions if p['direction'] in ('long', 'short')
    ) or "  (нет валидных мнений)"
    return (
        cut
        + "=== COUNCIL QUESTION ===\n"
        + question + "\n\n"
        + "=== YOUR COLLEAGUES' OPINIONS (Round 1) ===\n"
        + peers_text + "\n\n"
        + "=== YOUR TASK ===\n"
        + "You have heard your colleagues. Now give your FINAL answer.\n"
        + "You may keep your previous direction or change it if their arguments persuaded you.\n"
        + "Reply on ONE line in this EXACT format:\n"
        + "LONG: <one short sentence why> \n"
        + "OR\n"
        + "SHORT: <one short sentence why>\n"
        + "Keep the reasoning under 25 words. No markdown."
    )


def _ask_all_parallel(prompt: str, max_tokens: int = 100) -> list:
    """Запускает все 7 AI параллельно с указанным размером ответа. Возвращает список с direction+reason."""
    askers = {
        "ChatGPT":    ask_chatgpt,
        "Gemini":     ask_gemini,
        "Grok":       ask_grok,
        "DeepSeek":   ask_deepseek,
        "Groq":       ask_groq,
        "OpenRouter": ask_openrouter,
        "Mistral":    ask_mistral,
    }
    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futures = {ex.submit(fn, prompt, max_tokens): name for name, fn in askers.items()}
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            try:
                r = fut.result()
                d, reason = _parse_direction_and_reason(r.get("raw", ""))
                # если parse не сработал, используем поле direction из ответа
                if d == "unknown" and r.get("direction") in ("long", "short"):
                    d = r["direction"]
                out.append({
                    "name": name,
                    "direction": d,
                    "reason": reason,
                    "raw": r.get("raw", ""),
                    "error": r.get("error"),
                })
            except Exception as e:
                out.append({"name": name, "direction": "unknown", "reason": "", "raw": "", "error": str(e)})
    return out


def discuss_all_ai(price: float, candles_1m: list, candles_5m: list | None = None,
                   question: str | None = None, last_trade_analysis: str | None = None) -> dict:
    """
    Двухраундовое заседание AI совета.
    1. Каждый AI даёт направление + аргумент независимо.
    2. Каждому AI показываем мнения коллег и просим финальный ответ.
    last_trade_analysis — текстовый анализ предыдущей сделки, передаётся в раунд 1.
    """
    if not question:
        question = "Куда пойдёт цена ETH/USDT в следующие 10 минут — LONG или SHORT?"

    # ── Раунд 1 ──
    prompt1 = _build_council_prompt_round1(price, candles_1m, candles_5m, question, last_trade_analysis)
    round1 = _ask_all_parallel(prompt1, max_tokens=120)

    # Только AI с валидным направлением участвуют в раунде 2
    valid_peers = [r for r in round1 if r["direction"] in ("long", "short")]

    # ── Раунд 2 ──
    prompt2 = _build_council_prompt_round2(price, candles_1m, candles_5m, question, valid_peers)
    round2_raw = _ask_all_parallel(prompt2, max_tokens=120)

    # Сопоставляем по имени, помечаем changed=True если поменял мнение
    r1_by_name = {r["name"]: r for r in round1}
    round2 = []
    for r in round2_raw:
        prev = r1_by_name.get(r["name"], {})
        round2.append({
            **r,
            "changed": (
                prev.get("direction") in ("long", "short")
                and r["direction"] in ("long", "short")
                and prev["direction"] != r["direction"]
            ),
            "previous": prev.get("direction", "unknown"),
        })

    longs = sum(1 for r in round2 if r["direction"] == "long")
    shorts = sum(1 for r in round2 if r["direction"] == "short")
    responded = longs + shorts  # только AI которые дали валидный ответ
    # Консенсус = большинство из ответивших (>50%) И минимум 2 голоса
    MIN_VOTES = 2
    majority = (responded / 2) if responded > 0 else 999
    if longs >= MIN_VOTES and longs > majority and longs > shorts:
        consensus = "long"
    elif shorts >= MIN_VOTES and shorts > majority and shorts > longs:
        consensus = "short"
    else:
        consensus = "none"

    return {
        "question": question,
        "price": price,
        "round1": round1,
        "round2": round2,
        "consensus": consensus,
        "long_votes": longs,
        "short_votes": shorts,
        "timestamp": datetime.utcnow().isoformat(),
    }


def poll_all_ai(price: float, candles_1m: list, candles_5m: list | None = None) -> dict:
    prompt = _build_prompt(price, candles_1m, candles_5m)
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

    # Минимум 2 одинаковых голоса для открытия позиции
    MIN_VOTES = 2
    if longs >= MIN_VOTES and longs > shorts:
        consensus = "long"
    elif shorts >= MIN_VOTES and shorts > longs:
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
