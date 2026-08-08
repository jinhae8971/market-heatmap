#!/usr/bin/env python3
"""주요 지수 시계열 → docs/trend.json

왜 정규화가 핵심인가
  코스피 6,258과 닛케이 65,606을 같은 축에 그리면 아무것도 안 보인다.
  기간 시작을 100으로 맞춰야 "어느 시장이 더 올랐나"가 드러난다.
  정규화는 화면에서 하고, 여기서는 원계열만 보낸다 — 기간을 바꿀 때마다
  다시 받지 않고 클라이언트에서 다시 정규화하면 되기 때문이다.

왜 USD 환산이 필요한가
  코스피가 올라도 원화가 빠지면 달러 기준 수익률은 다르다. 국가 간 비교에서는
  이 차이가 결론을 뒤집는 경우가 흔하다. 그래서 환율 시계열을 함께 보낸다.
"""
from __future__ import annotations

import datetime as dt
import json
import os

import pandas as pd
import yfinance as yf

OUT = "docs/trend.json"
PERIOD = "5y"   # 화면에서 1M~5Y를 자르므로 넉넉히 받아 둔다

# (심볼, 표시명, 국가, 통화)
INDICES = [
    ("^GSPC", "S&P 500", "US", "USD"),
    ("^IXIC", "나스닥", "US", "USD"),
    ("^DJI", "다우", "US", "USD"),
    ("^RUT", "러셀 2000", "US", "USD"),
    ("^SOX", "필라델피아 반도체", "US", "USD"),
    ("^KS11", "코스피", "KR", "KRW"),
    ("^KQ11", "코스닥", "KR", "KRW"),
    ("^N225", "닛케이 225", "JP", "JPY"),
    ("1306.T", "토픽스 (ETF)", "JP", "JPY"),
    ("^TWII", "대만 가권", "TW", "TWD"),
    # 원자재 — 주식 지수와 함께 보면 위험선호/인플레 국면이 드러난다.
    # 전부 달러 표시라 USD 환산 토글의 영향을 받지 않는다.
    ("GC=F", "금", "CM", "USD"),
    ("SI=F", "은", "CM", "USD"),
    ("CL=F", "WTI 원유", "CM", "USD"),
]

# 국채 금리 — 가격이 아니라 '수익률(%)'이라 정규화 대상이 아니다.
# 100 기준 정규화를 하면 "금리가 2배 올랐다" 같은 무의미한 숫자가 나온다.
# 그래서 별도 패널에 절대값으로 그리고, 10Y-2Y 스프레드가 음수인 구간을
# 역전 구간으로 표시한다.
YIELDS = [
    ("^TNX", "미국 10년물", 10),
    ("2YY=F", "미국 2년물", 2),
]

# 국가별 통화 → USD 환산에 쓸 환율 심볼 (USD/XXX 호가이므로 나눈다)
FX = {"KRW": "KRW=X", "JPY": "JPY=X", "TWD": "TWD=X"}

# 화면 첫 진입 시 켜 둘 지수 — 너무 많으면 선이 엉킨다
DEFAULT_ON = {"^GSPC", "^SOX", "^KS11", "^N225", "^TWII", "GC=F"}


def series_of(frame: pd.DataFrame, sym: str) -> pd.Series | None:
    try:
        s = frame[sym].dropna()
    except KeyError:
        return None
    return s if not s.empty else None


def main() -> None:
    syms = [i[0] for i in INDICES]
    ysyms = [y[0] for y in YIELDS]
    raw = yf.download([*syms, *ysyms, *FX.values()], period=PERIOD,
                      progress=False, auto_adjust=True)["Close"]

    fx_series = {ccy: series_of(raw, sym) for ccy, sym in FX.items()}

    # 공통 날짜 축 — 시장마다 휴장일이 다르므로 합집합에 전진채움을 쓴다.
    # 교집합을 쓰면 한 시장의 휴장이 전체 데이터를 깎아먹는다.
    idx = None
    for sym in syms:
        s = series_of(raw, sym)
        if s is None:
            continue
        idx = s.index if idx is None else idx.union(s.index)
    if idx is None:
        raise RuntimeError("지수 시계열을 하나도 받지 못했습니다")
    idx = idx.sort_values()

    dates = [d.strftime("%Y-%m-%d") for d in idx]
    items = []

    for sym, name, country, ccy in INDICES:
        s = series_of(raw, sym)
        if s is None:
            print(f"[trend] {sym} 시계열 없음 — 제외")
            continue
        local = s.reindex(idx).ffill()

        usd = None
        if ccy == "USD":
            usd = local
        else:
            f = fx_series.get(ccy)
            if f is not None:
                usd = local / f.reindex(idx).ffill()
            else:
                print(f"[trend] {ccy} 환율 없음 — {sym} USD 환산 생략")

        items.append({
            "sym": sym, "name": name, "country": country, "ccy": ccy,
            "on": sym in DEFAULT_ON,
            "local": [None if pd.isna(v) else round(float(v), 2) for v in local],
            "usd": None if usd is None else
                   [None if pd.isna(v) else round(float(v), 6) for v in usd],
        })

    # 금리 패널 + 역전 구간
    yields, spread = [], []
    ymap = {}
    for sym, name, tenor in YIELDS:
        y = series_of(raw, sym)
        if y is None:
            print(f"[trend] {sym} 금리 시계열 없음 — 제외")
            continue
        aligned = y.reindex(idx).ffill()
        ymap[tenor] = aligned
        yields.append({
            "sym": sym, "name": name, "tenor": tenor,
            "values": [None if pd.isna(v) else round(float(v), 3) for v in aligned],
        })

    inversions = []
    if 10 in ymap and 2 in ymap:
        diff = (ymap[10] - ymap[2])
        spread = [None if pd.isna(v) else round(float(v), 3) for v in diff]
        # 역전(스프레드 < 0) 구간을 [시작, 끝] 인덱스 쌍으로 압축한다.
        # 하루짜리 노이즈는 버린다 — 화면에 실선처럼 보이기만 하고 의미가 없다.
        start = None
        for i, v in enumerate(diff):
            neg = (not pd.isna(v)) and v < 0
            if neg and start is None:
                start = i
            elif not neg and start is not None:
                if i - start >= 3:
                    inversions.append([start, i - 1])
                start = None
        if start is not None and len(diff) - start >= 3:
            inversions.append([start, len(diff) - 1])

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "dates": dates,
        "items": items,
        "yields": yields,
        "spread": spread,
        "inversions": inversions,
        "fx": {ccy: (None if s is None else round(float(s.dropna().iloc[-1]), 2))
               for ccy, s in fx_series.items()},
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, OUT)
    size = os.path.getsize(OUT) / 1024
    print(f"완료: {len(items)}개 지수 · 금리 {len(yields)}종 · "
          f"역전 {len(inversions)}구간 · {len(dates)}일 · {size:.0f}KB → {OUT}")


if __name__ == "__main__":
    main()
