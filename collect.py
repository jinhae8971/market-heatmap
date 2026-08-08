#!/usr/bin/env python3
"""히트맵 데이터 수집 → docs/heatmap.json

수집 원칙
  · fast_info만 쓴다. .info는 종목당 수 초라 136종목이면 워크플로우가 타임아웃난다.
  · 종목 단위 실패는 건너뛴다. 한 종목 때문에 전체 히트맵이 비면 안 된다.
  · 시총은 로컬통화로 오므로 USD로 환산해야 시장 간 면적 비교가 성립한다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
import yfinance as yf

from universe import MARKETS, PENCE, SHORT

OUT = "docs/heatmap.json"
FX_SYMBOLS = {"KRW": "KRW=X", "JPY": "JPY=X", "EUR": "EURUSD=X",
              "GBP": "GBPUSD=X", "CHF": "CHF=X", "DKK": "DKK=X"}
INVERTED = {"KRW", "JPY", "CHF", "DKK"}  # USD/XXX 호가


def fx_table() -> dict[str, float]:
    """통화 → USD 환산 계수."""
    out = {"USD": 1.0}
    for ccy, sym in FX_SYMBOLS.items():
        try:
            px = yf.Ticker(sym).fast_info.get("lastPrice")
            if not px:
                continue
            out[ccy] = (1.0 / px) if ccy in INVERTED else float(px)
        except Exception as exc:
            print(f"[fx] {ccy} 실패: {exc}")
    out["GBp"] = out.get("GBP", 0) / 100.0
    out["GBX"] = out["GBp"]
    return out


def perf_table(symbols: list[str]) -> dict[str, dict]:
    """종목별 기간 수익률(%). 히트맵에 '오늘'만 있으면 오늘 -1%가
    한 달간 +40% 뒤의 -1%인지 -30% 뒤의 -1%인지 구분되지 않는다."""
    try:
        raw = yf.download(symbols, period="1y", progress=False,
                          auto_adjust=True)["Close"]
    except Exception as exc:
        print(f"[perf] 가격 이력 실패: {exc}")
        return {}

    year = dt.date.today().year
    out: dict[str, dict] = {}
    for sym in symbols:
        try:
            ser = raw[sym].dropna()
        except (KeyError, TypeError):
            continue
        if len(ser) < 2:
            continue
        last = float(ser.iloc[-1])

        def back(days: int):
            if len(ser) <= days:
                return None
            return round(last / float(ser.iloc[-1 - days]) - 1, 4) * 100

        ytd = None
        cur = ser[ser.index >= pd.Timestamp(f"{year}-01-01", tz=ser.index.tz)]
        if len(cur) >= 2:
            ytd = round(last / float(cur.iloc[0]) - 1, 4) * 100

        out[sym] = {
            "d5": None if back(5) is None else round(back(5), 2),
            "d20": None if back(20) is None else round(back(20), 2),
            "ytd": None if ytd is None else round(ytd, 2),
        }
    return out


def fx_perf(fx_syms: dict[str, str]) -> dict[str, dict]:
    """통화별 기간 변동(%). USD 환산 수익률 = 현지 수익률 + 환율 변동.
    한국 투자자에게는 이 축이 결론을 바꾸는 경우가 많다."""
    if not fx_syms:
        return {}
    try:
        raw = yf.download(list(fx_syms.values()), period="1y",
                          progress=False, auto_adjust=True)["Close"]
    except Exception as exc:
        print(f"[fx] 환율 이력 실패: {exc}")
        return {}
    year = dt.date.today().year
    out = {}
    for ccy, sym in fx_syms.items():
        try:
            ser = raw[sym].dropna()
        except (KeyError, TypeError):
            continue
        if len(ser) < 2:
            continue
        # USD/XXX 호가이므로 뒤집어야 '달러로 환산했을 때의 변동'이 된다
        inv = 1.0 / ser
        last = float(inv.iloc[-1])

        def back(days):
            if len(inv) <= days:
                return None
            return round((last / float(inv.iloc[-1 - days]) - 1) * 100, 2)

        cur = inv[inv.index >= pd.Timestamp(f"{year}-01-01", tz=inv.index.tz)]
        out[ccy] = {
            "d1": back(1), "d5": back(5), "d20": back(20),
            "ytd": None if len(cur) < 2 else round((last / float(cur.iloc[0]) - 1) * 100, 2),
        }
    return out


def fetch_one(arg):
    sym, name, sector = arg
    try:
        fi = yf.Ticker(sym).fast_info
        last = fi.get("lastPrice")
        prev = fi.get("previousClose")
        cap = fi.get("marketCap")
        ccy = fi.get("currency") or "USD"
    except Exception as exc:
        print(f"[fetch] {sym} 실패: {exc}")
        return None
    if not last or not prev or not cap:
        print(f"[fetch] {sym} 데이터 결측 — 제외")
        return None
    return {"sym": sym, "name": name, "short": SHORT.get(sym, name),
            "sector": sector, "ccy": ccy,
            "price": round(float(last), 2), "cap_local": float(cap),
            "chg": round((float(last) / float(prev) - 1) * 100, 2)}


def _pc(row: dict, key: str):
    v = row.get(key)
    return None if v is None else round(float(v), 2)


def crypto(limit: int = 40) -> list[dict]:
    """CoinGecko 무료 엔드포인트. 429가 잦으므로 실패는 조용히 넘긴다."""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "order": "market_cap_desc",
                    "per_page": limit, "page": 1,
                    # 기간 히트맵을 쓰려면 주식과 같은 축이 필요하다
                    "price_change_percentage": "7d,30d,1y"},
            timeout=30, headers={"accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"[crypto] 수집 실패: {exc}")
        return []
    out = []
    for c in data:
        if not c.get("market_cap"):
            continue
        out.append({
            "sym": c["symbol"].upper(), "name": c["name"],
            "short": c["symbol"].upper(),
            "sector": "스테이블코인" if c["symbol"].lower() in
                      ("usdt", "usdc", "dai", "usde", "fdusd") else "암호화폐",
            "ccy": "USD", "price": c.get("current_price") or 0,
            "cap_local": float(c["market_cap"]), "cap_usd": float(c["market_cap"]),
            "chg": round(float(c.get("price_change_percentage_24h") or 0), 2),
            "d5": _pc(c, "price_change_percentage_7d_in_currency"),
            "d20": _pc(c, "price_change_percentage_30d_in_currency"),
            "ytd": _pc(c, "price_change_percentage_1y_in_currency"),
        })
    return out


def main() -> None:
    fx = fx_table()
    health = []
    markets: dict[str, dict] = {}
    all_syms = [t[0] for m in MARKETS.values() for t in m["items"]]
    perf = perf_table(all_syms)
    health.append({"step": "가격 이력", "ok": bool(perf), "n": len(perf)})

    with ThreadPoolExecutor(max_workers=8) as pool:
        for code, meta in MARKETS.items():
            rows = [r for r in pool.map(fetch_one, meta["items"]) if r]
            for r in rows:
                rate = fx.get(r["ccy"])
                if rate is None:
                    print(f"[fx] {r['ccy']} 환율 없음 — {r['sym']} USD 환산 생략")
                    rate = 0.0
                r["cap_usd"] = r["cap_local"] * rate
            for r in rows:
                r.update(perf.get(r["sym"], {"d5": None, "d20": None, "ytd": None}))
            rows.sort(key=lambda r: -r["cap_usd"])
            markets[code] = {"label": meta["label"], "items": rows}
            print(f"[{code}] {len(rows)}/{len(meta['items'])} 종목")

    health.append({"step": "주식 시세", "ok": True,
                   "n": sum(len(m["items"]) for m in markets.values())})

    coins = crypto()
    health.append({"step": "암호화폐", "ok": bool(coins), "n": len(coins)})
    if coins:
        markets["CRYPTO"] = {"label": "암호화폐", "items": coins}
        print(f"[CRYPTO] {len(coins)} 종목")

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "markets": markets,
        "fx": {k: round(v, 8) for k, v in fx.items()},
        "fx_perf": fx_perf(FX_SYMBOLS),
        "health": health,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = f"{OUT}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, OUT)
    total = sum(len(m["items"]) for m in markets.values())
    print(f"완료: {total}종목 → {OUT}")


if __name__ == "__main__":
    main()
