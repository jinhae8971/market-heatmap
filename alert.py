#!/usr/bin/env python3
"""이상 움직임 텔레그램 알림.

왜 필요한가
  앱을 열어야만 알 수 있으면 대부분의 날은 그냥 지나간다.
  '평소와 다른 날'만 골라 밀어주는 게 앱을 여는 이유가 된다.

발화 기준 — 셋 중 하나
  · 1일 등락이 ±5% 이상
  · 1주 등락이 ±12% 이상
  · 산업 계층 전체가 1일 ±3% 이상 (개별 종목이 아니라 계층이 움직인 날)
"""
from __future__ import annotations

import json
import os

import requests

D1, D5, TIER = 5.0, 12.0, 3.0


def load_config() -> dict:
    cfg = {"telegram_token": os.environ.get("TELEGRAM_TOKEN", ""),
           "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", "")}
    path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if k.lower() in cfg and not cfg[k.lower()]:
                    cfg[k.lower()] = v
        except (json.JSONDecodeError, OSError) as e:
            print(f"[config] 읽기 실패 - 환경변수만 사용: {e}")
    return cfg


def read(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[alert] {path} 읽기 실패: {exc}")
        return None


def build() -> str:
    lines = []
    hm = read("docs/heatmap.json")
    if hm:
        hits = []
        for code, m in hm["markets"].items():
            for r in m["items"]:
                d1, d5 = r.get("chg"), r.get("d5")
                why = ("1일" if d1 is not None and abs(d1) >= D1 else
                       "1주" if d5 is not None and abs(d5) >= D5 else None)
                if why:
                    hits.append((abs(d1 or 0), m["label"], r["short"], d1, d5, why))
        hits.sort(reverse=True)
        if hits:
            lines.append("<b>📈 이상 움직임</b>")
            for _, mkt, name, d1, d5, why in hits[:12]:
                mark = "🟢" if (d1 or 0) > 0 else "🔴"
                lines.append(f"  {mark} [{mkt}] {name} "
                             f"1일 {d1:+.1f}% · 1주 {(d5 if d5 is not None else 0):+.1f}% ({why})")

    si = read("docs/semi.json")
    if si:
        rot = []
        for name, ind in (si.get("industries") or {}).items():
            for t in ind.get("tiers", []):
                if t.get("d1") is not None and abs(t["d1"]) >= TIER:
                    rot.append(f"  {'🟢' if t['d1'] > 0 else '🔴'} {name}·{t['tier']} {t['d1']:+.2f}%")
        if rot:
            lines.append("")
            lines.append("<b>🏭 계층 단위 이동</b>")
            lines += rot[:8]

        # 이번 주 실적
        import datetime as dt
        today = dt.date.today()
        soon = []
        for name, ind in (si.get("industries") or {}).items():
            for r in ind.get("items", []):
                if not r.get("earn"):
                    continue
                dd = (dt.date.fromisoformat(r["earn"]) - today).days
                if 0 <= dd <= 7:
                    soon.append((dd, f"  D-{dd} {r['short']} ({name})"))
        if soon:
            lines.append("")
            lines.append("<b>📅 이번 주 실적</b>")
            lines += [t for _, t in sorted(set(soon))][:8]

    if not lines:
        return ""
    lines.insert(0, "")
    lines.insert(0, "<b>🔔 마켓 히트맵</b>")
    lines.append("")
    lines.append('<a href="https://jinhae8971.github.io/market-heatmap/">앱에서 보기</a>')
    return "\n".join(lines)


def main() -> None:
    msg = build()
    if not msg:
        print("[alert] 발화 조건 없음 - 발송 생략")
        return
    cfg = load_config()
    if not cfg["telegram_token"] or not cfg["telegram_chat_id"]:
        print("[telegram] 자격증명 없음 - 발송 생략")
        print(msg)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{cfg['telegram_token']}/sendMessage",
        json={"chat_id": cfg["telegram_chat_id"], "text": msg,
              "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20)
    r.raise_for_status()
    print("[telegram] 발송 완료")


if __name__ == "__main__":
    main()
