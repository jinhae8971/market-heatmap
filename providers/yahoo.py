"""Yahoo Finance (yfinance) — 개인 용도 전용.

yfinance 저장소가 명시하듯 이 API는 개인 용도로 의도된 것이고, 라이브러리 자체도
연구·교육 목적으로 배포된다. 그래서 commercial_ok = False다.
수익화 빌드에서 이 공급자를 고르면 get_provider()가 막는다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Sequence

import yfinance as yf

from .base import Quote, QuoteProvider

PAIR = {"KRW": "KRW=X", "JPY": "JPY=X", "EUR": "EURUSD=X", "GBP": "GBPUSD=X",
        "CHF": "CHF=X", "DKK": "DKK=X"}
INVERTED = {"KRW", "JPY", "CHF", "DKK"}


class YahooProvider(QuoteProvider):
    name = "yahoo"
    commercial_ok = False
    attribution = "데이터 제공: Yahoo Finance (개인 용도)"

    def _one(self, sym: str) -> tuple[str, Quote] | None:
        try:
            fi = yf.Ticker(sym).fast_info
            last, prev = fi.get("lastPrice"), fi.get("previousClose")
            if not last or not prev:
                return None
            return sym, Quote(sym, float(last), float(prev),
                              fi.get("marketCap"), fi.get("currency") or "USD")
        except Exception as exc:
            print(f"[yahoo] {sym} 실패: {exc}")
            return None

    def quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        with ThreadPoolExecutor(max_workers=8) as pool:
            return dict(r for r in pool.map(self._one, symbols) if r)

    def fx(self, pairs: Sequence[str]) -> dict[str, float]:
        out = {"USD": 1.0}
        for ccy in pairs:
            sym = PAIR.get(ccy)
            if not sym:
                continue
            try:
                px = yf.Ticker(sym).fast_info.get("lastPrice")
                if px:
                    out[ccy] = (1.0 / px) if ccy in INVERTED else float(px)
            except Exception as exc:
                print(f"[yahoo/fx] {ccy} 실패: {exc}")
        out["GBp"] = out.get("GBP", 0) / 100.0
        out["GBX"] = out["GBp"]
        return out
