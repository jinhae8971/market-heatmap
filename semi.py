#!/usr/bin/env python3
"""반도체 밸류체인 트레이딩 지표 → docs/semi.json

왜 히트맵과 분리했나
  히트맵은 "지금 뭐가 오르내리나"를 본다. 반도체 트레이더가 실제로 판단할 때
  필요한 건 그게 아니라 **밸류체인 어느 계층에 돈이 도는가**다.
  장비가 먼저 움직이고 메모리가 따라가는지, 팹리스만 오르고 나머지가 안 따라오는지가
  같은 등락률이라도 완전히 다른 신호다. 그래서 계층(tier)을 1급 개념으로 둔다.

계층 순서는 밸류체인 상류 → 하류다. 화면에서도 이 순서를 유지한다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import yfinance as yf

import memshare

OUT = "docs/semi.json"
BENCH = "^SOX"  # 필라델피아 반도체 지수 — 이 업종의 기준선

# (티커, 표시명, 축약명, 국가)
TIERS: dict[str, list[tuple[str, str, str, str]]] = {
    "장비": [
        ("ASML.AS", "ASML", "ASML", "EU"),
        ("AMAT", "어플라이드머티어리얼즈", "AMAT", "US"),
        ("LRCX", "램리서치", "램리서치", "US"),
        ("KLAC", "KLA", "KLA", "US"),
        ("8035.T", "도쿄일렉트론", "도쿄일렉", "JP"),
        ("6146.T", "디스코", "디스코", "JP"),
        ("6857.T", "어드반테스트", "어드반", "JP"),
        ("7735.T", "스크린홀딩스", "스크린", "JP"),
    ],
    "소재·부품": [
        ("4063.T", "신에쓰화학", "신에쓰", "JP"),
        ("3436.T", "SUMCO", "SUMCO", "JP"),
        ("042700.KS", "한미반도체", "한미반도", "KR"),
        ("058470.KQ", "리노공업", "리노공업", "KR"),
        ("357780.KQ", "솔브레인", "솔브레인", "KR"),
        ("240810.KQ", "원익IPS", "원익IPS", "KR"),
    ],
    "파운드리": [
        ("TSM", "TSMC", "TSMC", "US"),
        ("UMC", "UMC", "UMC", "US"),
        ("GFS", "글로벌파운드리", "GF", "US"),
        ("000990.KS", "DB하이텍", "DB하이텍", "KR"),
    ],
    "메모리": [
        ("005930.KS", "삼성전자", "삼성전자", "KR"),
        ("000660.KS", "SK하이닉스", "하이닉스", "KR"),
        ("MU", "마이크론", "마이크론", "US"),
        ("285A.T", "키오시아", "키오시아", "JP"),
        ("SNDK", "샌디스크", "샌디스크", "US"),
    ],
    "팹리스·로직": [
        ("NVDA", "엔비디아", "엔비디아", "US"),
        ("AMD", "AMD", "AMD", "US"),
        ("AVGO", "브로드컴", "브로드컴", "US"),
        ("QCOM", "퀄컴", "퀄컴", "US"),
        ("INTC", "인텔", "인텔", "US"),
        ("ARM", "ARM", "ARM", "US"),
        ("MRVL", "마벨", "마벨", "US"),
    ],
    "AI 수요": [
        ("MSFT", "마이크로소프트", "MS", "US"),
        ("GOOGL", "알파벳", "구글", "US"),
        ("AMZN", "아마존", "아마존", "US"),
        ("META", "메타", "메타", "US"),
    ],
}

FX_SYMBOLS = {"KRW": "KRW=X", "JPY": "JPY=X", "EUR": "EURUSD=X"}
INVERTED = {"KRW", "JPY"}


def fx_table() -> dict[str, float]:
    out = {"USD": 1.0}
    for ccy, sym in FX_SYMBOLS.items():
        try:
            px = yf.Ticker(sym).fast_info.get("lastPrice")
            if px:
                out[ccy] = (1 / px) if ccy in INVERTED else float(px)
        except Exception as exc:
            print(f"[fx] {ccy} 실패: {exc}")
    return out


def ytd(series: pd.Series) -> float | None:
    """연초 대비 수익률(%). 기준은 올해 첫 거래일 종가."""
    s = series.dropna()
    if s.empty:
        return None
    year = dt.date.today().year
    this_year = s[s.index >= pd.Timestamp(f"{year}-01-01", tz=s.index.tz)]
    if this_year.empty or len(this_year) < 2:
        return None
    return round(float(s.iloc[-1] / this_year.iloc[0] - 1) * 100, 2)


def ret(series: pd.Series, days: int) -> float | None:
    """days 거래일 전 대비 수익률(%). 데이터가 모자라면 None."""
    s = series.dropna()
    if len(s) <= days:
        return None
    return round(float(s.iloc[-1] / s.iloc[-1 - days] - 1) * 100, 2)


def fetch(args):
    sym, name, short, country, tier, hist, bench_ret = args
    s = hist.get(sym)
    if s is None or s.dropna().empty:
        print(f"[semi] {sym} 가격 없음 — 제외")
        return None
    s = s.dropna()

    tk = yf.Ticker(sym)
    try:
        info = tk.info
    except Exception as exc:
        print(f"[semi] {sym} info 실패: {exc}")
        info = {}

    # .info의 marketCap은 종목·시점에 따라 비어 있다(예: MU). fast_info로 보완한다.
    # 이 값이 비면 시총 점유율 파이에서 그 회사가 통째로 사라진다.
    cap = info.get("marketCap")
    if not cap:
        try:
            cap = tk.fast_info.get("marketCap")
        except Exception:
            cap = None
    if not cap:
        print(f"[semi] {sym} 시총 결측 — 점유율 집계에서 빠짐")

    px = float(s.iloc[-1])
    hi52 = info.get("fiftyTwoWeekHigh") or float(s.max())
    r = {d: ret(s, d) for d in (1, 5, 20, 60)}

    # 20일 상대강도 — SOX 대비 초과수익. 업종 전체가 오른 건지 이 종목이 센 건지 구분한다
    rs = None
    if r[20] is not None and bench_ret.get(20) is not None:
        rs = round(r[20] - bench_ret[20], 2)

    daily = s.pct_change().dropna().tail(20)
    vol = round(float(daily.std() * np.sqrt(252) * 100), 1) if len(daily) > 5 else None

    return {
        "sym": sym, "name": name, "short": short, "country": country, "tier": tier,
        "price": round(px, 2),
        "ccy": info.get("currency") or "USD",
        "cap_local": cap,
        "d1": r[1], "d5": r[5], "d20": r[20], "d60": r[60],
        "ytd": ytd(s),
        "rs20": rs,
        "from_high": round((px / float(hi52) - 1) * 100, 1) if hi52 else None,
        "vol20": vol,
        "fpe": round(info.get("forwardPE"), 1) if info.get("forwardPE") else None,
        "pbr": round(info.get("priceToBook"), 2) if info.get("priceToBook") else None,
        "gm": round(info.get("grossMargins") * 100, 1) if info.get("grossMargins") else None,
    }


# 영업이익률 추이를 볼 대상 — 메모리 5사
MARGIN_TARGETS = [
    ("005930.KS", "삼성전자"), ("000660.KS", "SK하이닉스"), ("MU", "마이크론"),
    ("285A.T", "키오시아"), ("SNDK", "샌디스크"),
]


def margin_rows(stmt) -> list[dict]:
    """손익계산서에서 영업이익률만 뽑는다. 열은 최신순이라 뒤집어 시간순으로 만든다."""
    if stmt is None or stmt.empty:
        return []
    if "Total Revenue" not in stmt.index or "Operating Income" not in stmt.index:
        return []
    out = []
    for col in reversed(list(stmt.columns)):
        rev = stmt.loc["Total Revenue", col]
        op = stmt.loc["Operating Income", col]
        if pd.isna(rev) or pd.isna(op) or not rev:
            continue
        out.append({"period": col.strftime("%Y-%m"),
                    "margin": round(float(op) / float(rev) * 100, 1)})
    return out


def margins() -> list[dict]:
    """연간·분기 영업이익률.

    한계를 화면에도 적어야 한다.
      · 삼성전자·SK하이닉스는 전사 기준이라 메모리 사업부만의 수치가 아니다
      · 회계연도 기준이 회사마다 달라(마이크론 8월, 샌디스크 6월) 같은 해도 시점이 다르다
      · yfinance가 주는 과거 기간이 회사마다 3~5년으로 들쭉날쭉하다
    """
    out = []
    for sym, name in MARGIN_TARGETS:
        tk = yf.Ticker(sym)
        try:
            ann = margin_rows(tk.income_stmt)
            qtr = margin_rows(tk.quarterly_income_stmt)
        except Exception as exc:
            print(f"[margin] {sym} 실패: {exc}")
            continue
        if not ann and not qtr:
            print(f"[margin] {sym} 손익 데이터 없음 — 제외")
            continue
        out.append({"sym": sym, "name": name, "annual": ann, "quarterly": qtr})
        print(f"[margin] {name} 연간 {len(ann)}기 · 분기 {len(qtr)}기")
    return out


def main() -> None:
    syms = [t[0] for tier in TIERS.values() for t in tier]
    # YTD를 계산해야 하므로 연초부터 확보한다. 6개월로는 1월이 안 들어온다.
    raw = yf.download([*syms, BENCH], period="1y", progress=False,
                      auto_adjust=True)["Close"]
    hist = {c: raw[c] for c in raw.columns}

    bench = hist.get(BENCH)
    bench_ret = {d: ret(bench, d) for d in (1, 5, 20, 60)} if bench is not None else {}
    bench_ytd = ytd(bench) if bench is not None else None

    jobs = [(sym, name, short, country, tier, hist, bench_ret)
            for tier, rows in TIERS.items() for sym, name, short, country in rows]
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(fetch, jobs) if r]

    fx = fx_table()
    for r in rows:
        rate = fx.get(r["ccy"], 0.0)
        r["cap_usd"] = round(r["cap_local"] * rate, 0) if r["cap_local"] else None

    # 계층 집계 — 시총가중. 단순평균을 쓰면 소형주가 계층 방향을 뒤집는다
    tiers = []
    for tier in TIERS:
        members = [r for r in rows if r["tier"] == tier]
        if not members:
            continue
        agg = {"tier": tier, "count": len(members)}
        for k in ("d1", "d5", "d20"):
            vals = [(r[k], r["cap_usd"] or 0) for r in members if r[k] is not None]
            wsum = sum(w for _, w in vals)
            agg[k] = round(sum(v * w for v, w in vals) / wsum, 2) if wsum else None
        agg["cap_usd"] = sum(r["cap_usd"] or 0 for r in members)
        tiers.append(agg)

    # 시총 점유율 — 매일 도는 자동 지표. 매출 점유율과 성격이 다르므로 분리해 담는다
    mem = [r for r in rows if r["tier"] == "메모리" and r.get("cap_usd")]
    mem_total = sum(r["cap_usd"] for r in mem)
    cap_share = [{"name": r["short"], "sym": r["sym"],
                  "share": round(r["cap_usd"] / mem_total * 100, 1),
                  "cap_usd": r["cap_usd"], "d20": r["d20"]}
                 for r in sorted(mem, key=lambda x: -x["cap_usd"])] if mem_total else []

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "bench": {"sym": BENCH, "name": "필라델피아 반도체지수",
                  "level": round(float(bench.dropna().iloc[-1]), 2) if bench is not None else None,
                  **{k: v for k, v in bench_ret.items()}},
        "tier_order": list(TIERS),
        "tiers": tiers,
        "items": rows,
        "memory": {"cap_share": cap_share, **memshare.build(),
                   "margins": margins()},
    }
    # bench_ret의 키가 int라 JSON에서 문자열이 된다. 명시적으로 정리한다
    payload["bench"] = {
        "sym": BENCH, "name": "필라델피아 반도체지수",
        "level": payload["bench"]["level"],
        "d1": bench_ret.get(1), "d5": bench_ret.get(5),
        "d20": bench_ret.get(20), "d60": bench_ret.get(60),
        "ytd": bench_ytd,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, OUT)
    print(f"완료: {len(rows)}종목 · {len(tiers)}계층 → {OUT}")


if __name__ == "__main__":
    main()
