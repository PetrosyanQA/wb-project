"""Единый объект решения по товару (аудит 2026-11-02): ворота → TEST / SOURCE / SCALE / WATCHLIST / HOLD / REJECT.

    python -m src.decision                  # текущий товар из config/decision_current.yaml
    python -m src.decision --json

Правила (решение не может обогнать доказательства):
  юридический FAIL или любой FAIL / уникальность REJECT → REJECT
  UNKNOWN по спросу, уникальности, поставщику, экономике → HOLD
  экономика / поставщик ESTIMATE                         → WATCHLIST (можно запросить КП и образец, нельзя платить партию)
  уникальность SIGNAL_ONLY                               → WATCHLIST
  нет образца                                            → нельзя SOURCE (максимум «заказать образец»)
  нет тестовых продаж                                    → нельзя SCALE
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")
CFG = Path(__file__).resolve().parents[1] / "config" / "decision_current.yaml"
CORE = ("external_demand", "wb_demand", "uniqueness", "supplier", "economics", "legal")


def load(path: Path = CFG) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def decide(c: dict) -> dict:
    g = {k: (v or {}).get("status", "UNKNOWN") for k, v in (c.get("gates") or {}).items()}
    s = lambda k: g.get(k, "UNKNOWN")                                          # noqa: E731
    blocked, nxt = [], ""
    if s("legal") == "FAIL" or s("uniqueness") == "REJECT" or any(s(k) == "FAIL" for k in CORE):
        return _out(c, g, "REJECT", "HIGH", [k for k in CORE if s(k) in ("FAIL", "REJECT")], "товар закрываем, следующий из копилки")
    blocked = [k for k in CORE if s(k) in ("UNKNOWN", "HOLD")]
    if blocked:
        return _out(c, g, "HOLD", "LOW", blocked, f"добыть данные: {', '.join(blocked)}")
    est = [k for k in ("supplier", "economics") if s(k) == "ESTIMATE"]
    if est or s("uniqueness") == "SIGNAL_ONLY":
        blocked = est + (["uniqueness"] if s("uniqueness") == "SIGNAL_ONLY" else [])
        return _out(c, g, "WATCHLIST", "MEDIUM", blocked,
                    "получить КП с нужной комплектацией и заказать образец (партию не оплачивать)")
    if s("sample") != "PASS":
        return _out(c, g, "SOURCE", "MEDIUM", ["sample"], "заказать и проверить образец по жалобам")
    if s("test_sales") != "PASS":
        return _out(c, g, "TEST", "MEDIUM", ["test_sales"], "тестовая партия 50–100 шт → живая карточка → 30 дней → kill_rules")
    return _out(c, g, "SCALE", "HIGH", [], "основная партия по config/launch.yaml")


def discovery_warning(c: dict, today: dt.date | None = None) -> str:
    """Поиск без даты окончания = бесконечный анализ (исследование ИИ-агентов 02.11): цикл DISCOVERY обязан кончиться решением."""
    if c.get("mode") != "DISCOVERY":
        return ""
    until = c.get("discovery_until")
    if not until:
        return "⚠️ режим DISCOVERY без discovery_until — задайте дату решения go/no-go"
    until = until if isinstance(until, dt.date) else dt.date.fromisoformat(str(until))
    left = (until - (today or dt.date.today())).days
    if left < 0:
        return f"⛔ цикл поиска закончился {until}: принять решение go/no-go по лучшему кандидату, новый поиск не начинать"
    return f"цикл поиска до {until} (осталось {left} дн.), затем решение go/no-go"


def _out(c, g, decision, conf, blocked, nxt) -> dict:
    return {"product": c.get("current_product"), "niche": c.get("current_niche"), "mode": c.get("mode"),
            "decision": decision, "confidence": conf, "gates": g, "blocked_by": blocked, "next_action": nxt,
            "discovery": discovery_warning(c)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--config", default=str(CFG))
    a = ap.parse_args()
    d = decide(load(Path(a.config)))
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return
    print(f"{d['product']} (ниша {d['niche']}), режим {d['mode']}")
    if d["discovery"]:
        print(d["discovery"])
    print(f"РЕШЕНИЕ: {d['decision']} (уверенность {d['confidence']})")
    for k, v in d["gates"].items():
        print(f"  {k:<16} {v}")
    print(f"Блокирует: {', '.join(d['blocked_by']) or '—'}\nСледующее действие: {d['next_action']}")


if __name__ == "__main__":
    main()
