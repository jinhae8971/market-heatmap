"""시세 공급자 추상화.

이 레이어가 존재하는 이유는 하나다. **상업화의 병목은 코드가 아니라 데이터 라이선스**다.
현재 쓰는 Yahoo(yfinance)는 비공식 엔드포인트이고 개인 용도로만 허용된다.
광고나 구독으로 수익을 내는 순간 공급자를 교체해야 하는데, 그때 수집기 전체를
다시 쓰지 않아도 되도록 인터페이스를 여기서 고정한다.

교체 시 바꾸는 것: 환경변수 MARKET_DATA_PROVIDER 하나.
"""
from __future__ import annotations

import os

from .base import Quote, QuoteProvider, ProviderLicenseError
from .yahoo import YahooProvider
from .rest import RestProvider

REGISTRY = {
    "yahoo": YahooProvider,
    "polygon": lambda: RestProvider("polygon"),
    "twelvedata": lambda: RestProvider("twelvedata"),
    "fmp": lambda: RestProvider("fmp"),
}


def get_provider() -> QuoteProvider:
    """환경변수로 공급자를 고른다. 상업 모드에서는 개인용 공급자를 거부한다."""
    name = os.environ.get("MARKET_DATA_PROVIDER", "yahoo").lower()
    commercial = os.environ.get("COMMERCIAL_MODE", "0") == "1"

    if name not in REGISTRY:
        raise ValueError(f"알 수 없는 공급자: {name} (가능: {', '.join(REGISTRY)})")

    provider = REGISTRY[name]()
    if commercial and not provider.commercial_ok:
        raise ProviderLicenseError(
            f"'{name}'은 개인 용도 라이선스입니다. 수익화 빌드에서는 쓸 수 없습니다.\n"
            "MARKET_DATA_PROVIDER를 라이선스 계약이 있는 공급자로 바꾸세요."
        )
    return provider
