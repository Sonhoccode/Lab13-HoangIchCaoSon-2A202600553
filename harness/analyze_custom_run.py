from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> int:
    telemetry_path = Path(sys.argv[1] if len(sys.argv) > 1 else "solution/telemetry.jsonl")
    if not telemetry_path.exists():
        print(f"missing telemetry: {telemetry_path}")
        return 1

    events = [json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_qid = {event.get("qid"): event for event in events}
    failures = []

    for qid, event in sorted(by_qid.items()):
        question = event.get("question", "")
        answer = _answer_from_run(qid) or ""
        trace = event.get("trace", [])
        expected = _expected(question, trace)
        pii = bool(re.search(r"[\w.+-]+@[\w.-]+\.\w+|\b0\d{8,10}\b", answer))
        total = _extract_total(answer)

        ok = True
        reason = []
        if expected["kind"] == "total" and total != expected["value"]:
            ok = False
            reason.append(f"total {total} != {expected['value']}")
        if expected["kind"] == "refuse" and total is not None:
            ok = False
            reason.append("refusal contains total")
        if pii:
            ok = False
            reason.append("PII leak")

        status = "OK" if ok else "BAD"
        print(f"{status} {qid}: {answer[:100]}")
        if reason:
            print(f"  reason: {', '.join(reason)}")
            failures.append(qid)

    print(f"\nsummary: {len(events) - len(failures)}/{len(events)} passed local checks")
    return 1 if failures else 0


def _answer_from_run(qid: str) -> str | None:
    path = Path("run_output.json")
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data.get("results", []):
        if row.get("qid") == qid:
            return row.get("answer")
    return None


def _expected(question: str, trace: list[dict]) -> dict:
    stock = _obs(trace, "check_stock")
    if not stock:
        return {"kind": "unknown"}
    if not stock.get("found", True) or not stock.get("in_stock", False):
        return {"kind": "refuse"}

    qty = _quantity(question)
    available = stock.get("quantity")
    if available is not None and qty > int(available):
        return {"kind": "refuse"}

    if "mua" not in _strip(question):
        return {"kind": "stock"}

    unit = int(stock["unit_price_vnd"])
    discount = _obs(trace, "get_discount") or {}
    pct = int(discount.get("percent", 0)) if discount.get("valid") else 0

    shipping_fee = 0
    if re.search(r"\b(ship|giao)\b", _strip(question)):
        shipping = _obs(trace, "calc_shipping")
        if not shipping or shipping.get("available") is False:
            return {"kind": "refuse"}
        shipping_fee = int(shipping.get("cost_vnd") or shipping.get("fee_vnd") or 0)

    subtotal = unit * qty
    return {"kind": "total", "value": subtotal * (100 - pct) // 100 + shipping_fee}


def _obs(trace: list[dict], tool: str) -> dict | None:
    for step in trace:
        if step.get("tool") == tool and isinstance(step.get("observation"), dict):
            return step["observation"]
    return None


def _quantity(question: str) -> int:
    match = re.search(r"\bmua\s+(\d+)\b", _strip(question))
    return int(match.group(1)) if match else 1


def _extract_total(answer: str) -> int | None:
    matches = re.findall(r"(\d[\d.]*)\s*VND", answer or "")
    if not matches:
        return None
    return int(re.sub(r"\D", "", matches[-1]))


def _strip(text: str) -> str:
    table = str.maketrans(
        "áàảãạăắằẳẵặâấầẩẫậđéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ",
        "aaaaaaaaaaaaaaaaadeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyy",
    )
    return text.lower().translate(table)


if __name__ == "__main__":
    raise SystemExit(main())
