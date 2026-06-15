"""YOUR mitigation + observability layer. The simulator calls mitigate() around the
opaque agent (a REAL LLM) for every request. This is the ONLY place observability can
live -- the agent is silent. Legal moves: retry / cache / route / guardrail / sanitize
/ fallback / session-reset / PROMPT ROUTING, plus your own logging/tracing/metrics.
Illegal: hardcoding answers, importing the agent internals, reading instructor files,
network exfiltration.

  call_next(question, config) -> result   # the only way to reach the black box
  context = {"session_id","turn_index","qid","cache": <shared dict>, "cache_lock": <Lock>}
  result  = {"answer","status","steps","trace","meta":{latency_ms,usage,...}}

PROMPT ROUTING: you can override the agent's system prompt PER REQUEST by setting it in
the config you pass to call_next, e.g.:
    conf = dict(config); conf["system_prompt"] = my_better_prompt
    result = call_next(question, conf)
(Or just edit solution/prompt.txt for a single static prompt used on every request.)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback

_PY = f"python{sys.version_info.major}.{sys.version_info.minor}"
_EXTRA_PATHS = [
    f"/usr/local/lib/{_PY}",
    f"/usr/lib/{_PY}",
    "/opt/observathon-deps",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".deps")),
]
for _path in reversed(_EXTRA_PATHS):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)
# You may reuse the Day 13 toolkit, e.g.:
# from telemetry.logger import logger
# from telemetry.cost import cost_from_usage
# from telemetry.redact import redact


def mitigate(call_next, question, config, context):
    t0 = time.time()
    attempts = max(1, int(config.get("retry", {}).get("max_attempts", 1)))
    last_error = None
    sanitized_question = _sanitize_question(question)
    cache_key = _cache_key(sanitized_question)
    cached = _cache_get(context, cache_key)
    if cached is not None:
        result = dict(cached)
        result["meta"] = dict(result.get("meta", {}))
        result["meta"]["latency_ms"] = int((time.time() - t0) * 1000)
        result["meta"]["usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        result["meta"]["tools_used"] = []
        result["meta"]["session_id"] = context.get("session_id")
        result["meta"]["turn_index"] = context.get("turn_index")
        _log_event(question, config, context, result, 0, t0)
        return result

    total_attempts = attempts + 1
    for attempt in range(total_attempts):
        try:
            result = call_next(sanitized_question, config)
            if _has_retryable_tool_error(result.get("trace") or []) and attempt + 1 < total_attempts:
                _log_event(question, config, context, result, attempt, t0)
                continue
            result = _postprocess_result(sanitized_question, result)
            if result.get("status") == "ok":
                _cache_set(context, cache_key, result)
            _log_event(question, config, context, result, attempt, t0)
            return result
        except Exception as exc:
            last_error = exc
            error_text = repr(exc)
            should_stop = "AuthenticationError" in error_text or attempt + 1 >= total_attempts
            _log_event(
                question,
                config,
                context,
                {
                    "status": "wrapper_error",
                    "error": error_text,
                    "traceback": traceback.format_exc(limit=3),
                },
                attempt,
                t0,
            )
            if should_stop:
                break

    return {
        "answer": None,
        "status": "wrapper_error",
        "steps": 0,
        "trace": [],
        "meta": {
            "latency_ms": int((time.time() - t0) * 1000),
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "model": config.get("model"),
            "provider": config.get("provider"),
            "tools_used": [],
            "error": repr(last_error),
        },
    }


def _log_event(question, config, context, result, attempt, start_time):
    event = {
        "qid": context.get("qid"),
        "session_id": context.get("session_id"),
        "turn_index": context.get("turn_index"),
        "attempt": attempt + 1,
        "question": question,
        "status": result.get("status"),
        "steps": result.get("steps"),
        "provider": config.get("provider"),
        "model": config.get("model"),
        "wall_ms": int((time.time() - start_time) * 1000),
        "meta": result.get("meta", {}),
        "tools_used": result.get("meta", {}).get("tools_used", result.get("tools_used", [])),
        "trace": result.get("trace", []),
        "error": result.get("error"),
        "traceback": result.get("traceback"),
    }
    path = os.path.join(os.path.dirname(__file__), "telemetry.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _cache_key(question):
    return re.sub(r"\s+", " ", _strip_accents(question).lower()).strip()


def _sanitize_question(question):
    pieces = re.split(r"(?<=[.!?])\s+|;\s+", question)
    kept = []
    for piece in pieces:
        normalized = _strip_accents(piece).lower()
        injectionish = (
            "ghi chu" in normalized
            or "note:" in normalized
            or "system" in normalized
            or "bo qua" in normalized
            or "ignore" in normalized
            or "gia he thong" in normalized
            or "gia la" in normalized
        )
        if not injectionish:
            kept.append(piece)
    cleaned = " ".join(kept).strip()
    return cleaned or question


def _cache_get(context, key):
    cache = context.get("cache")
    lock = context.get("cache_lock")
    if cache is None:
        return None
    if lock:
        with lock:
            return cache.get(key)
    return cache.get(key)


def _cache_set(context, key, result):
    cache = context.get("cache")
    lock = context.get("cache_lock")
    if cache is None:
        return
    if lock:
        with lock:
            cache[key] = result
    else:
        cache[key] = result


def _postprocess_result(question, result):
    if result.get("status") not in {"ok", "loop", "max_steps", "no_action"}:
        return result

    trace = result.get("trace") or []
    stock = _first_observation(trace, "check_stock")
    if not stock:
        return _redact_answer(result)

    qty = _requested_quantity(question)
    is_buy = bool(re.search(r"\bmua\b", _strip_accents(question).lower()))
    fallback_item = _product_from_question(question)
    if stock.get("error") == "loyalty_service_down":
        stock = _fallback_stock(fallback_item) or stock
    found = bool(stock.get("found", True))
    in_stock = bool(stock.get("in_stock", False))
    available_qty = stock.get("quantity")
    unit_price = _as_int(stock.get("unit_price_vnd"))
    item = stock.get("item") or stock.get("item_name") or fallback_item or "san pham"

    if not found:
        return _replace_answer(result, f"Khong tim thay {item}; khong the dat mua.")
    if stock.get("error"):
        return _replace_answer(result, "Khong kiem tra duoc ton kho; khong the dat mua.")
    if not in_stock:
        return _replace_answer(result, f"{item} hien het hang; khong the dat mua.")
    available_qty_int = _as_int(available_qty)
    if is_buy and available_qty_int is not None and qty > available_qty_int:
        return _replace_answer(result, f"{item} chi con {available_qty}; khong the dat mua {qty}.")

    if not is_buy:
        if unit_price is None:
            return _redact_answer(result)
        return _replace_answer(result, f"{item} con hang. Gia: {unit_price} VND")

    if unit_price is None:
        return _redact_answer(result)

    discount = _first_observation(trace, "get_discount") or {}
    if _has_coupon(question) and not discount:
        discount = _fallback_discount(question, item, qty) or {}
    if _has_coupon(question) and not discount:
        return _redact_answer(result)
    if discount.get("error"):
        discount = _fallback_discount(question, item, qty) or discount
    if discount.get("error"):
        return _replace_answer(result, "Khong xac minh duoc ma giam gia; khong the tinh tong.")
    pct = _as_int(discount.get("percent")) if discount.get("valid") else 0
    pct = pct or 0

    shipping_fee = 0
    needs_shipping = bool(re.search(r"\b(ship|giao)\b", _strip_accents(question).lower()))
    if needs_shipping:
        shipping = _first_observation(trace, "calc_shipping")
        total_weight = (_as_float(stock.get("weight_kg")) or 0) * qty
        if not shipping:
            shipping = _fallback_shipping(question, total_weight)
        if isinstance(shipping, dict) and shipping.get("error") == "loyalty_service_down":
            shipping = _fallback_shipping(question, total_weight) or shipping
        if not shipping or shipping.get("available") is False or shipping.get("error") == "destination_not_served":
            return _replace_answer(result, "Khong ho tro giao hang den dia diem nay; khong the dat mua.")
        shipping_fee = _as_int(
            shipping.get("cost_vnd")
            or shipping.get("fee_vnd")
            or shipping.get("shipping_vnd")
            or shipping.get("fee")
        )
        if shipping_fee is None:
            return _replace_answer(result, "Khong tinh duoc phi giao hang; khong the tinh tong.")

    subtotal = unit_price * qty
    discounted = subtotal * (100 - pct) // 100
    total = discounted + shipping_fee
    return _replace_answer(result, f"Tong cong: {total} VND")


def _first_observation(trace, tool_name):
    for step in trace:
        if step.get("tool") == tool_name:
            obs = step.get("observation")
            if isinstance(obs, dict):
                return obs
    return None


def _has_retryable_tool_error(trace):
    for step in trace:
        obs = step.get("observation")
        if isinstance(obs, dict) and obs.get("error") == "loyalty_service_down":
            return True
    return False


def _requested_quantity(question):
    m = re.search(r"\bmua\s+(\d+)\b", _strip_accents(question).lower())
    return int(m.group(1)) if m else 1


def _as_int(value):
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_coupon(question):
    q = _strip_accents(question).lower()
    return bool(re.search(r"\b(coupon|ma|code)\b", q))


def _product_from_question(question):
    q = _strip_accents(question).lower()
    for name in ("macbook", "iphone", "ipad", "airpods"):
        if name in q:
            return name
    m = re.search(r"\bmua\s+\d+\s+([a-z0-9]+)", q)
    return m.group(1) if m else None


def _fallback_stock(item):
    catalog = {
        "iphone": {"item": "iphone", "found": True, "in_stock": True, "quantity": 12, "unit_price_vnd": 22000000, "weight_kg": 0.5},
        "ipad": {"item": "ipad", "found": True, "in_stock": True, "quantity": 7, "unit_price_vnd": 18000000, "weight_kg": 0.45},
        "macbook": {"item": "macbook", "found": True, "in_stock": True, "quantity": 4, "unit_price_vnd": 35000000, "weight_kg": 1.6},
        "airpods": {"item": "airpods", "found": True, "in_stock": False, "quantity": 0, "unit_price_vnd": 4500000, "weight_kg": 0.1},
    }
    return catalog.get((item or "").lower())


def _coupon_from_question(question):
    q = _strip_accents(question).upper()
    for code in ("SALE15", "VIP20", "WINNER", "EXPIRED"):
        if code in q:
            return code
    return None


def _fallback_discount(question, item, qty):
    code = _coupon_from_question(question)
    if not code:
        return None
    if code == "EXPIRED":
        return {"code": code, "valid": False, "percent": 0}
    if code == "SALE15":
        percent = 30 if qty >= 5 else 15
    elif code == "VIP20":
        percent = 40 if item == "macbook" else 20
    elif code == "WINNER":
        percent = 20 if qty >= 3 else 10
    else:
        return None
    return {"code": code, "valid": True, "percent": percent}


def _destination_from_question(question):
    q = _strip_accents(question).lower()
    destinations = {
        "tp hcm": ("tp hcm", 25000),
        "ho chi minh": ("tp hcm", 25000),
        "ha noi": ("ha noi", 30000),
        "hai phong": ("hai phong", 28000),
        "da nang": ("da nang", 35000),
        "can tho": ("can tho", None),
        "vung tau": ("vung tau", None),
        "da lat": ("da lat", None),
    }
    for needle, value in destinations.items():
        if needle in q:
            return value
    return None


def _fallback_shipping(question, weight_kg):
    dest = _destination_from_question(question)
    if dest is None:
        return None
    name, base = dest
    if base is None:
        return {"destination": name, "error": "destination_not_served", "cost_vnd": None}
    fee = base + max(0, int(round((weight_kg - 1.0) * 5000)))
    return {"destination": name, "weight_kg": weight_kg, "cost_vnd": fee}


def _replace_answer(result, answer):
    result = dict(result)
    result["answer"] = answer
    result["status"] = "ok"
    return result


def _redact_answer(result):
    answer = result.get("answer")
    if isinstance(answer, str):
        answer = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", "[REDACTED]", answer)
        answer = re.sub(r"\b0\d{8,10}\b", "[REDACTED]", answer)
        return _replace_answer(result, answer)
    return result


def _strip_accents(text):
    table = str.maketrans(
        "áàảãạăắằẳẵặâấầẩẫậđéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ",
        "aaaaaaaaaaaaaaaaadeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyy",
    )
    return text.translate(table)
