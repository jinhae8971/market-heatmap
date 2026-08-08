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
# 5년 추이를 그리려면 그보다 1년 더 받아야 한다.
# 롤링 250일 백분위는 첫 1년치를 소모하기 때문이다.
LOOKBACK = "8y"   # 롤링 2년 백분위가 첫 2년을 소모하므로 5년 추이엔 8년이 필요하다
HIST_DAYS = 1260         # 약 5년(거래일)
BENCH_IDX = {"미국": "^IXIC", "한국": "^KS11", "반도체": "^SOX"}

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

# 반도체 — 업종 하나를 따로 보는 이유는, 지수 센티멘트가 좋아도
# 이 업종만 이탈하는(또는 그 반대인) 국면이 자주 나오기 때문이다.
RATIOS_SEMI = [
    ("반도체 / S&P 500", "SOXX", "SPY", "업종으로 돈이 오는가"),
    ("장비 / 팹리스", "AMAT", "NVDA", "상류가 하류를 따라오는가"),
    ("메모리 / 로직", "MU", "AVGO", "사이클 민감 구간 선호"),
    ("반도체 / 금", "SOXX", "GC=F", "안전자산 대비 업종 선호"),
]

# 3배 롱/숏 ETF 거래대금 비율 — 반도체는 개인 레버리지 수요가 가장 몰리는 업종이다
LEV_SEMI = ("SOXL", "SOXS")

# 쏠림도: 엔비디아 / 업종. 하나가 끌면 폭이 좁다는 뜻이라 역방향으로 쓴다
CONC_SEMI = ("NVDA", "SOXX")

RV_SEMI = "SOXX"

SEMI_BREADTH = ["NVDA", "AMD", "AVGO", "QCOM", "INTC", "MU", "TSM", "TXN",
                "AMAT", "LRCX", "KLAC", "MRVL", "ASML.AS", "8035.T", "6857.T",
                "005930.KS", "000660.KS"]

VOL_US = "^VIX"
FX_KR = "KRW=X"          # 원화 약세 = 위험회피


PCT_WINDOW = 504   # 약 2년(거래일)


def pct_rank(series: pd.Series) -> float | None:
    """마지막 값의 최근 2년 대비 백분위(0~100).

    데이터는 5년 추이를 위해 6년치를 받지만, 현재 점수의 기준은 2년으로 고정한다.
    기준 기간이 바뀌면 같은 지표가 다른 점수로 나와 과거 판단과 비교가 안 된다.
    """
    s = series.dropna().tail(PCT_WINDOW)
    if len(s) < 60:
        return None
    return round(float((s < s.iloc[-1]).mean()) * 100, 1)


SMOOTH = 5   # 거래일. 하루짜리 갭을 지우되 국면 정보는 남기는 최소 구간


SMOOTH_FLOW = 20   # 거래대금처럼 하루 편차가 큰 계열용


def smooth(s: pd.Series, window: int = SMOOTH) -> pd.Series:
    """비율 지표를 5일 평균으로 다듬는다.

    코스피가 하루 ±18% 움직이는 국면에서는 비율이 하루 만에 백분위 0↔100을
    오간다. 그러면 종합지수가 수직으로 튀어 추세를 전혀 읽을 수 없다.
    심리는 하루 만에 뒤집히는 게 아니므로 짧은 평균으로 갭을 흡수한다.
    """
    return s.rolling(window, min_periods=1).mean()


def ratio_series(px: pd.DataFrame, num: str, den: str) -> pd.Series | None:
    try:
        a, b = px[num].dropna(), px[den].dropna()
    except KeyError:
        return None
    idx = a.index.intersection(b.index)
    if len(idx) < 60:
        return None
    return smooth((a.reindex(idx) / b.reindex(idx)).dropna())


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
    # 거래대금은 하루 편차가 비율 지표의 4배다. 5일로는 부족해 20일로 다듬는다.
    # 진단 결과 이 항목 하나가 한국 종합지수의 수직 스파이크를 만들고 있었다.
    return smooth((a.reindex(idx) / tot.replace(0, np.nan)).dropna(), SMOOTH_FLOW)


def realized_vol(px: pd.DataFrame, sym: str, window: int = 20) -> pd.Series | None:
    """실현변동성(연율). 지수 옵션 변동성을 못 받을 때 쓰는 대용치."""
    try:
        s = px[sym].dropna()
    except KeyError:
        return None
    if len(s) < window + 40:
        return None
    return smooth((s.pct_change().rolling(window).std() * np.sqrt(252) * 100).dropna())


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
            v = smooth(px[vol_sym].dropna())
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
            f = smooth(px[fx_sym].dropna())
            r = pct_rank(f)
            if r is not None:
                # USD/KRW가 높을수록 원화 약세 = 위험회피
                comps.append({"label": "원화 강세", "score": round(100 - r, 1),
                              "note": f"USD/KRW {float(f.iloc[-1]):,.0f} · 강할수록 위험선호",
                              "value": round(float(f.iloc[-1]), 1), "d20": None})
        except KeyError:
            pass

    if name == "반도체":
        lev = lev_ratio(px, vol_df, *LEV_SEMI) if vol_df is not None else None
        if lev is not None:
            r = pct_rank(lev)
            if r is not None:
                comps.append({"label": "SOXL / SOXS", "score": r,
                              "note": "3배 롱·숏 ETF 거래대금 비율",
                              "value": round(float(lev.iloc[-1]) * 100, 1), "d20": None})
        conc = ratio_series(px, *CONC_SEMI)
        if conc is not None:
            r = pct_rank(conc)
            if r is not None:
                # 한 종목이 업종을 끌면 폭이 좁다 — 탐욕이 아니라 취약함이다
                comps.append({"label": "엔비디아 쏠림", "score": round(100 - r, 1),
                              "display": r, "invert": True,
                              "note": "엔비디아 / 반도체ETF · 높을수록 쏠림",
                              "value": round(float(conc.iloc[-1]), 4), "d20": None})
        rv = realized_vol(px, RV_SEMI)
        if rv is not None:
            r = pct_rank(rv)
            if r is not None:
                comps.append({"label": "변동성", "score": round(100 - r, 1),
                              "display": r, "invert": True,
                              "note": f"반도체ETF 20일 연율 {float(rv.iloc[-1]):.0f}% · 높을수록 공포",
                              "value": round(float(rv.iloc[-1]), 1), "d20": None})

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
        # 당일 상승 비율은 하루 노이즈라 종합에서 뺀다.
        # 넣으면 추이(과거 시계열)와 구성요소가 달라져 두 화면이 어긋난다.
        comps.append({"label": "오늘 상승 종목", "score": adv, "in_score": False,
                      "note": "당일 참여 폭 · 종합에는 미반영", "value": adv, "d20": None})

    scored = [c for c in comps if c.get("in_score", True)]
    total = round(sum(c["score"] for c in scored) / len(scored), 1) if scored else None
    return {"name": name, "score": total, "components": comps}


def roll_pct(s: pd.Series) -> pd.Series:
    """롤링 백분위. 창 길이를 현재 점수(PCT_WINDOW)와 맞춰야
    추이의 마지막 값과 화면 상단의 종합 점수가 일치한다."""
    return s.rolling(PCT_WINDOW, min_periods=120).apply(
        lambda w: (w < w.iloc[-1]).mean() * 100, raw=False)


def breadth_series(px: pd.DataFrame, symbols: list[str]) -> pd.Series | None:
    """20일선 위 종목 비율의 시계열. 현재 점수에만 있고 추이에 없으면
    두 화면이 서로 다른 지표가 된다."""
    cols = [c for c in symbols if c in px.columns]
    if len(cols) < 5:
        return None
    sub = px[cols]
    above = (sub > sub.rolling(20, min_periods=20).mean()).sum(axis=1)
    valid = sub.rolling(20, min_periods=20).mean().notna().sum(axis=1)
    return smooth((above / valid.replace(0, np.nan) * 100).dropna())


def history(px: pd.DataFrame, ratios, vol_sym: str | None,
            idx_sym: str | None = None, extra: list[pd.Series] | None = None,
            breadth_syms: list[str] | None = None) -> list[dict]:
    """종합지수 추이 + 같은 날짜의 지수 종가.

    지수를 함께 실어야 '센티멘트가 지수를 이끄는가, 따라가는가'를 볼 수 있다.
    센티멘트만 그린 그래프는 예쁘지만 판단에 쓰이지 않는다."""
    parts = []
    for _, num, den, _ in ratios:
        ser = ratio_series(px, num, den)
        if ser is not None:
            parts.append(roll_pct(ser))
    if vol_sym:
        try:
            parts.append(100 - roll_pct(smooth(px[vol_sym].dropna())))
        except KeyError:
            pass
    for ser in (extra or []):
        if ser is not None:
            parts.append(ser)
    if breadth_syms:
        b = breadth_series(px, breadth_syms)
        if b is not None:
            parts.append(b)
    if not parts:
        return []
    df = pd.concat(parts, axis=1).dropna(how="all")
    # 종합에 5일 평균을 한 번 더 건다. 구성요소를 다듬어도 8개 백분위의 평균은
    # 여전히 튄다 — 한 지표가 임계를 넘나들면 백분위가 계단식으로 움직이기 때문이다.
    # 화면 상단의 현재 점수도 이 계열의 마지막 값을 쓴다(아래 main 참고).
    avg = df.mean(axis=1).rolling(SMOOTH, min_periods=1).mean().dropna().tail(HIST_DAYS)

    idx = None
    if idx_sym:
        try:
            idx = px[idx_sym].reindex(avg.index).ffill()
        except KeyError:
            print(f"[sent] {idx_sym} 지수 없음 — 추이에 지수 미표시")

    out = []
    for i, x in avg.items():
        row = {"d": i.strftime("%Y-%m-%d"), "v": round(float(x), 1)}
        if idx is not None and not pd.isna(idx.get(i, np.nan)):
            row["p"] = round(float(idx[i]), 2)
        out.append(row)
    return out


def forward_stats(hist: list[dict]) -> dict:
    """센티멘트 수준과 '이후' 수익률의 관계.

    동시점 상관은 거의 항상 양수로 나온다 — 오르면 심리가 좋아지니 당연하다.
    판단에 쓰이는 건 '지금 수준이 앞으로 무엇을 뜻하는가'이므로 선행 관계를 본다.
    """
    rows = [h for h in hist if "p" in h]
    if len(rows) < 300:
        return {}
    v = np.array([h["v"] for h in rows], dtype=float)
    p = np.array([h["p"] for h in rows], dtype=float)

    out = {"n": len(rows)}
    for horizon in (20, 60):
        fwd = np.full(len(p), np.nan)
        fwd[:-horizon] = (p[horizon:] / p[:-horizon] - 1) * 100
        mask = ~np.isnan(fwd)
        if mask.sum() < 100:
            continue
        out[f"corr{horizon}"] = round(float(np.corrcoef(v[mask], fwd[mask])[0, 1]), 3)

        buckets = []
        for lo, hi in [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]:
            sel = mask & (v >= lo) & (v < hi)
            if sel.sum() >= 20:
                buckets.append({"range": f"{lo}~{hi if hi <= 100 else 100}",
                                "n": int(sel.sum()),
                                "avg": round(float(np.nanmean(fwd[sel])), 2)})
        out[f"buckets{horizon}"] = buckets

    # 동시점 상관도 참고로 남긴다 (20일 수익률 기준)
    ret20 = np.full(len(p), np.nan)
    ret20[20:] = (p[20:] / p[:-20] - 1) * 100
    m2 = ~np.isnan(ret20)
    if m2.sum() > 100:
        out["corr_same"] = round(float(np.corrcoef(v[m2], ret20[m2])[0, 1]), 3)
    return out


def main() -> None:
    import universe

    kr_syms = [t[0] for t in universe.KR][:30]
    us_syms = [t[0] for t in universe.US][:30]

    need = sorted({s for _, a, b, _ in RATIOS_US + RATIOS_KR for s in (a, b)}
                  | {s for _, a, b, _ in RATIOS_SEMI for s in (a, b)}
                  | {VOL_US, FX_KR, RV_KR, RV_SEMI} | set(LEV_KR) | set(LEV_SEMI)
                  | set(CONC_SEMI) | set(BENCH_IDX.values())
                  | set(kr_syms) | set(us_syms) | set(SEMI_BREADTH))
    raw = yf.download(need, period=LOOKBACK, progress=False, auto_adjust=True)
    px = raw["Close"]
    vol_df = raw["Volume"]

    us = build_market("미국", px, RATIOS_US, us_syms, VOL_US, None)
    kr = build_market("한국", px, RATIOS_KR, kr_syms, None, FX_KR, vol_df)
    se = build_market("반도체", px, RATIOS_SEMI, SEMI_BREADTH, None, None, vol_df)

    # 추이는 현재 점수와 같은 구성요소로 만든다.
    # 예전에는 추이가 비율 4개만 써서, 하나가 극단으로 가면 종합이 수직으로 튀었다.
    kr_extra = []
    lev = lev_ratio(px, vol_df, *LEV_KR)
    if lev is not None:
        kr_extra.append(roll_pct(lev))
    rv = realized_vol(px, RV_KR)
    if rv is not None:
        kr_extra.append(100 - roll_pct(rv))
    try:
        kr_extra.append(100 - roll_pct(smooth(px[FX_KR].dropna())))
    except KeyError:
        pass

    se_extra = []
    slev = lev_ratio(px, vol_df, *LEV_SEMI)
    if slev is not None:
        se_extra.append(roll_pct(slev))
    sconc = ratio_series(px, *CONC_SEMI)
    if sconc is not None:
        se_extra.append(100 - roll_pct(sconc))
    srv = realized_vol(px, RV_SEMI)
    if srv is not None:
        se_extra.append(100 - roll_pct(srv))

    hist = {"미국": history(px, RATIOS_US, VOL_US, BENCH_IDX["미국"],
                          breadth_syms=us_syms),
            "한국": history(px, RATIOS_KR, None, BENCH_IDX["한국"],
                          extra=kr_extra, breadth_syms=kr_syms),
            "반도체": history(px, RATIOS_SEMI, None, BENCH_IDX["반도체"],
                           extra=se_extra, breadth_syms=SEMI_BREADTH)}

    # 현재 점수 = 추이의 마지막 값. 두 곳에서 따로 계산하면 반드시 어긋난다.
    for m in (us, kr, se):
        h = hist.get(m["name"]) or []
        if h:
            m["score"] = h[-1]["v"]

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "markets": [us, kr, se],
        "history": hist,
        "stats": {k: forward_stats(v) for k, v in hist.items()},
        "bench_idx": BENCH_IDX,
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
    print(f"완료: 미국 {us['score']} / 한국 {kr['score']} / 반도체 {se['score']} → {OUT}")


if __name__ == "__main__":
    main()
