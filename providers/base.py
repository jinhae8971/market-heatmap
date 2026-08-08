"""공급자 인터페이스 — 수집기가 의존하는 유일한 계약."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence


class ProviderLicenseError(RuntimeError):
    """라이선스 조건에 맞지 않는 사용을 막는다."""


@dataclass(slots=True)
class Quote:
    symbol: str
    price: float
    prev_close: float
    market_cap: float | None
    currency: str

    @property
    def change_pct(self) -> float:
        if not self.prev_close:
            return 0.0
        return (self.price / self.prev_close - 1) * 100


class QuoteProvider(ABC):
    name: str = "base"
    #: 상업적 재배포가 허용된 공급자인지. 수익화 빌드에서 이 값을 검사한다.
    commercial_ok: bool = False
    #: 화면에 표기해야 하는 출처 문구 (대부분의 라이선스가 요구한다)
    attribution: str = ""

    @abstractmethod
    def quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        """심볼 → Quote. 개별 실패는 결과에서 빼고 예외를 올리지 않는다."""

    @abstractmethod
    def fx(self, pairs: Sequence[str]) -> dict[str, float]:
        """통화 코드 → USD 환산 계수."""
