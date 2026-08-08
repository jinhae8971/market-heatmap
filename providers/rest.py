"""라이선스 계약이 있는 REST 공급자용 범용 어댑터.

Polygon·Twelve Data·FMP는 응답 형태만 다를 뿐 필요한 필드는 동일하다.
그래서 개별 클래스를 만들지 않고 스펙 테이블로 처리한다.
새 공급자를 붙이려면 SPECS에 항목 하나를 추가하면 된다.

주의: 상업 이용 여부(commercial_ok)는 코드가 아니라 **계약**이 정한다.
여기 True로 적힌 것은 '유료 상업 플랜 가입을 전제로 한다'는 뜻이지,
가입 없이 쓰면 된다는 뜻이 아니다.
"""
from __future__ import annotations

import os
from typing import Sequence

import requests

from .base import Quote, QuoteProvider, ProviderLicenseError

SPECS = {
    "polygon": {
        "quote_url": "https://api.polygon.io/v2/snapshot/locale/global/markets/stocks/tickers/{sym}",
        "key_param": "apiKey",
        "env": "POLYGON_API_KEY",
        "attribution": "데이터 제공: Polygon.io",
        "path": {"price": ("ticker", "day", "c"),
                 "prev": ("ticker", "prevDay", "c")},
    },
    "twelvedata": {
        "quote_url": "https://api.twelvedata.com/quote?symbol={sym}",
        "key_param": "apikey",
        "env": "TWELVEDATA_API_KEY",
        "attribution": "데이터 제공: Twelve Data",
        "path": {"price": ("close",), "prev": ("previous_close",)},
    },
    "fmp": {
        "quote_url": "https://financialmodelingprep.com/api/v3/quote/{sym}",
        "key_param": "apikey",
        "env": "FMP_API_KEY",
        "attribution": "데이터 제공: Financial Modeling Prep",
        "path": {"price": (0, "price"), "prev": (0, "previousClose"),
                 "cap": (0, "marketCap")},
    },
}


def _dig(obj, path):
    for k in path:
        if obj is None:
            return None
        obj = obj[k] if isinstance(k, int) else obj.get(k)
    return obj


class RestProvider(QuoteProvider):
    commercial_ok = True

    def __init__(self, name: str) -> None:
        if name not in SPECS:
            raise ValueError(f"스펙 없음: {name}")
        self.name = name
        self.spec = SPECS[name]
        self.attribution = self.spec["attribution"]
        self.key = os.environ.get(self.spec["env"], "")
        if not self.key:
            raise ProviderLicenseError(
                f"{name} 사용에는 {self.spec['env']} 환경변수(API 키)가 필요합니다."
            )

    def quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for sym in symbols:
            url = self.spec["quote_url"].format(sym=sym)
            try:
                r = requests.get(url, params={self.spec["key_param"]: self.key},
                                 timeout=20)
                r.raise_for_status()
                data = r.json()
            except Exception as exc:
                print(f"[{self.name}] {sym} 실패: {exc}")
                continue
            price = _dig(data, self.spec["path"]["price"])
            prev = _dig(data, self.spec["path"]["prev"])
            cap = _dig(data, self.spec["path"].get("cap", ())) if "cap" in self.spec["path"] else None
            if not price or not prev:
                continue
            out[sym] = Quote(sym, float(price), float(prev),
                             float(cap) if cap else None, "USD")
        return out

    def fx(self, pairs: Sequence[str]) -> dict[str, float]:
        raise NotImplementedError(
            f"{self.name} 환율 엔드포인트는 계약 플랜에 따라 달라집니다. "
            "계약 확정 후 이 메서드만 구현하면 됩니다."
        )
