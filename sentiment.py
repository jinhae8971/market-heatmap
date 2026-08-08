#!/usr/bin/env python3
"""투자자 센티멘트 → docs/sentiment.json

무엇을 재는가
  '심리'를 직접 재는 지표(AAII 설문, CNN Fear&Greed, 신용잔고, 투자자예탁금)는
  무료 API로 자동 수집할 경로가 없다. 그래서 **가격에 이미 드러난 위험선호**를
  구성요소로 계산한다. 설문 대신 돈이 실제로 어디에 있는지를 본다.

  · 변동성 — VIX가 낮으면 안심, 높으면 공포
  · 위험선호 비율 — 고베타/저변동, 성장/가치, 소형/대형, 하이일드/투자등급
  · 폭 — 20일선 위 종목 비율, 상승 종목 비율
  · 안전자산 — 금 대비 주식, 원화 강약

각 구성요소를 0~100으로 환산해 평균 낸다. 100에 가까울수록 위험선호(탐욕),
0에 가까울수록 위험회피(공포)다.

한계는 화면에도 적는다.
  · 설문 기반 심리지표가 아니라 가격 기반 대리지표다
  · 한국은 VKOSPI·신용잔고를 못 받아 구성요소가 미국보다 적다
"""
from __future__ import annotations

import datetime as dt
import json
import os

import numpy as np
import pandas as pd
import yfinance as yf

OUT = "docs/sentiment.json"
LOOKBACK = "2y"          # 백분위 계산에 쓸 기간
HIST_DAYS = 180          # 화면에 그릴 종합지수 추이

# 비율형 구성요소: (이름, 분자, 분모, 설명)
RATIOS_US = [
    ("고베타 / 저변동", "SPHB", "SPLV", "위험을 살수록 오른다"),
    ("성장 / 가치", "IWF", "IWD", "성장주 선호"),
    ("소형 / 대형", "IWM", "SPY", "소형주 선호"),
    ("하이일드 / 투자등급", "HYG", "LQD", "신용위험 감수"),
    ("주식 / 금", "SPY", "GC=F", "안전자산 대비 주식 선호"),
]
RATIOS_KR = [
    ("코스닥 / 코스피", "^KQ11", "^KS11", "개인 비중이 높은 코스닥 선호"),
    ("코스피 / 금", "^KS11", "GC=F", "안전자산 대비 주식 선호"),
    ("한국 / 신흥국", "EWY", "EEM", "신흥국 중 한국을 골라 사는가"),
    ("코스닥150 / 코스피200", "229200.KS", "069500.KS", "중소형 성장 선호"),
]

# 레버리지·인버스 ETF 거래대금 비율 — 한국 개인 투기 심리의 대리지표.
# 설문 대신 실제 베팅 방향을 본다. 레버리지 쪽이 커질수록 위험선호.
LEV_KR = ("122630.KS", "114800.KS")

# 실현변동성 — VKOSPI를 무료로 받을 수 없어 지수 자체의 20일 변동성으로 대신한다
RV_KR = "^KS11"

VOL_US = "^VIX"
FX_KR = "KRW=X"          # 원화 약세 = 위험회피


def pct_rank(series: pd.Series) -> float | None:
    """마지막 값의 과거 대비 백분위(0~100)."""
    s = series.dropna()
    if len(s) < 60:
        return None
    return round(float((s < s.iloc[-1]).mean()) * 100, 1)


def ratio_series(px: pd.DataFrame, num: str, den: str) -> pd.Series | None:
    try:
        a, b = px[num].dropna(), px[den].dropna()
    except KeyError:
        return None
    idx = a.index.intersection(b.index)
    if len(idx) < 60:
        return None
    return (a.reindex(idx) / b.reindex(idx)).dropna()


def breadth(px: pd.DataFrame, symbols: list[str]) -> tuple[float | None, float | None]:
    """20일선 위 비율, 오늘 상승 비율. 지수는 올랐는데 폭이 좁으면 심리는 다르다."""
    above, up, n = 0, 0, 0
    for sym in symbols:
        try:
            s = px[sym].dropna()
        except KeyError:
            continue
        if len(s) < 21:
            continue
        n += 1
        if float(s.iloc[-1]) > float(s.tail(20).mean()):
            above += 1
        if float(s.iloc[-1]) > float(s.iloc[-2]):
            up += 1
    if not n:
        return None, None
    return round(above / n * 100, 1), round(up / n * 100, 1)


def lev_ratio(px: pd.DataFrame, vol: pd.DataFrame,
              lev: str, inv: str) -> pd.Series | None:
    """레버리지 ETF 거래대금 / (레버리지+인버스). 0.5보다 크면 상승 베팅 우위."""
    try:
        a = (px[lev] * vol[lev]).dropna()
        b = (px[inv] * vol[inv]).dropna()
    except KeyError:
        return None
    idx = a.index.intersection(b.index)
    if len(idx) < 60:
        return None
    tot = a.reindex(idx) + b.reindex(idx)
    return (a.reindex(idx) / tot.replace(0, np.nan)).dropna()


def realized_vol(px: pd.DataFrame, sym: str, window: int = 20) -> pd.Series | None:
    """실현변동성(연율). 지수 옵션 변동성을 못 받을 때 쓰는 대용치."""
    try:
        s = px[sym].dropna()
    except KeyError:
        return None
    if len(s) < window + 40:
        return None
    return (s.pct_change().rolling(window).std() * np.sqrt(252) * 100).dropna()


def build_market(name: str, px: pd.DataFrame, ratios, breadth_syms,
                 vol_sym: str | None, fx_sym: str | None,
                 vol_df: pd.DataFrame | None = None) -> dict:
    comps = []

    for label, num, den, note in ratios:
        ser = ratio_series(px, num, den)
        if ser is None:
            print(f"[sent] {name} {label} 계산 불가")
            continue
        score = pct_rank(ser)
        if score is None:
            continue
        comps.append({"label": label, "score": score, "note": note,
                      "value": round(float(ser.iloc[-1]), 4),
                      "d20": round(float(ser.iloc[-1] / ser.iloc[-21] - 1) * 100, 2)
                      if len(ser) > 21 else None})

    if vol_sym:
        try:
            v = px[vol_sym].dropna()
            r = pct_rank(v)
            if r is not None:
                # 변동성은 이름 그대로 '변동성'으로 보여준다.
                # 화면에는 백분위(display)를, 종합 평균에는 뒤집은 값(score)을 쓴다.
                # 이름과 숫자가 반대를 가리키면 읽는 사람이 매번 헷갈린다.
                comps.append({"label": "변동성", "score": round(100 - r, 1),
                              "display": r, "invert": True,
                              "note": f"VIX {float(v.iloc[-1]):.1f} · 높을수록 공포",
                              "value": round(float(v.iloc[-1]), 2), "d20": None})
        except KeyError:
            print(f"[sent] {name} 변동성 지표 없음")

    if fx_sym:
        try:
            f = px[fx_sym].dropna()
            r = pct_rank(f)
            if r is not None:
                # USD/KRW가 높을수록 원화 약세 = 위험회피
                comps.append({"label": "원화 강세", "score": round(100 - r, 1),
                              "note": f"USD/KRW {float(f.iloc[-1]):,.0f} · 강할수록 위험선호",
                              "value": round(float(f.iloc[-1]), 1), "d20": None})
        except KeyError:
            pass

    if name == "한국":
        lev = lev_ratio(px, vol_df, *LEV_KR) if vol_df is not None else None
        if lev is not None:
            r = pct_rank(lev)
            if r is not None:
                comps.append({"label": "레버리지 / 인버스", "score": r,
                              "note": "개인이 어느 쪽에 베팅하는가",
                              "value": round(float(lev.iloc[-1]) * 100, 1),
                              "d20": None})
        rv = realized_vol(px, RV_KR)
        if rv is not None:
            r = pct_rank(rv)
            if r is not None:
                # 변동성이 극단일 때는 최대 일간 변동을 함께 실어 준다.
                # 처음엔 데이터 오류를 의심했으나 실제 값으로 확인됐다(2026-08).
                # 이상해 보이는 값을 임의로 깎지 않는다 — 그 극단 자체가 신호다.
                try:
                    mx = float(px[RV_KR].dropna().pct_change().tail(20).abs().max() * 100)
                except Exception:
                    mx = None
                comps.append({"label": "실현변동성", "score": round(100 - r, 1),
                              "display": r, "invert": True,
                              "note": (f"코스피 20일 연율 {float(rv.iloc[-1]):.0f}%"
                                       f" · 하루 ±{float(rv.iloc[-1])/15.87:.1f}% 수준"
                                       " · 높을수록 공포"),
                              "value": round(float(rv.iloc[-1]), 1), "d20": None,
                              "flag": (None if mx is None or mx < 6
                                       else f"최근 20일 최대 일간 변동 {mx:.1f}%")})

    ma, adv = breadth(px, breadth_syms)
    if ma is not None:
        comps.append({"label": "20일선 위 종목", "score": ma,
                      "note": "상승의 폭이 넓은가", "value": ma, "d20": None})
    if adv is not None:
        comps.append({"label": "오늘 상승 종목", "score": adv,
                      "note": "당일 참여 폭", "value": adv, "d20": None})

    total = round(sum(c["score"] for c in comps) / len(comps), 1) if comps else None
    return {"name": name, "score": total, "components": comps}


def history(px: pd.DataFrame, ratios, vol_sym: str | None) -> list[dict]:
    """종합지수 추이. 구성요소별 롤링 백분위를 매일 평균한다."""
    parts = []
    for _, num, den, _ in ratios:
        ser = ratio_series(px, num, den)
        if ser is None:
            continue
        parts.append(ser.rolling(250, min_periods=60)
                     .apply(lambda w: (w < w.iloc[-1]).mean() * 100, raw=False))
    if vol_sym:
        try:
            v = px[vol_sym].dropna()
            parts.append(100 - v.rolling(250, min_periods=60)
                         .apply(lambda w: (w < w.iloc[-1]).mean() * 100, raw=False))
        except KeyError:
            pass
    if not parts:
        return []
    df = pd.concat(parts, axis=1).dropna(how="all")
    avg = df.mean(axis=1).dropna().tail(HIST_DAYS)
    return [{"d": i.strftime("%Y-%m-%d"), "v": round(float(x), 1)}
            for i, x in avg.items()]


def main() -> None:
    import universe

    kr_syms = [t[0] for t in universe.KR][:30]
    us_syms = [t[0] for t in universe.US][:30]

    need = sorted({s for _, a, b, _ in RATIOS_US + RATIOS_KR for s in (a, b)}
                  | {VOL_US, FX_KR, RV_KR} | set(LEV_KR) | set(kr_syms) | set(us_syms))
    raw = yf.download(need, period=LOOKBACK, progress=False, auto_adjust=True)
    px = raw["Close"]
    vol_df = raw["Volume"]

    us = build_market("미국", px, RATIOS_US, us_syms, VOL_US, None)
    kr = build_market("한국", px, RATIOS_KR, kr_syms, None, FX_KR, vol_df)

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "markets": [us, kr],
        "history": {"미국": history(px, RATIOS_US, VOL_US),
                    "한국": history(px, RATIOS_KR, None)},
        "kr_note": ("VKOSPI·신용잔고·투자자예탁금은 무료 API로 받을 수 없어 "
                    "레버리지/인버스 거래대금 비율과 실현변동성으로 대신한다."),
        "note": ("설문 기반 심리지표가 아니라 가격에 드러난 위험선호를 계산한 대리지표다. "
                 "구성요소마다 2년 백분위를 0~100으로 환산해 평균했다."),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, OUT)
    print(f"완료: 미국 {us['score']} / 한국 {kr['score']} → {OUT}")


if __name__ == "__main__":
    main()
