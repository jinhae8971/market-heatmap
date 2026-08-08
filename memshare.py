"""메모리 매출 점유율 — 손으로 관리하는 분기 데이터.

왜 자동 수집이 아닌가
  DRAM/NAND 매출 점유율은 주가 API에서 나오지 않는다. TrendForce·Omdia·
  카운터포인트 같은 조사기관의 분기 리포트가 원천이고, 무료로 자동 수집할 경로가 없다.
  그래서 여기에 출처와 함께 손으로 적고, 화면에서도 "분기 데이터·수동 갱신"임을
  명시한다. 자동으로 도는 시총 점유율과 섞이면 안 되기 때문이다.

갱신 방법
  분기 리포트가 나오면 QUARTERS 맨 뒤에 한 줄 추가하고 SOURCE의 날짜를 고친다.
  확인하지 못한 업체는 넣지 않는다 — 빈칸은 '기타'로 흡수된다.
"""
from __future__ import annotations

SOURCE = {
    "name": "카운터포인트리서치 메모리 트래커",
    "note": "매출액 기준 · 반올림으로 합계가 100%가 아닐 수 있음",
    "checked": "2026-08-08",
}

# 표시명 → 화면 색까지 여기서 고정한다. 분기마다 색이 바뀌면 추세를 못 읽는다
VENDORS = ["삼성전자", "SK하이닉스", "마이크론", "CXMT", "기타"]

# 분기 → {업체: 점유율%}. 확인된 값만 적는다.
DRAM_QUARTERS = [
    ("2025 Q1", {"삼성전자": 34, "SK하이닉스": 36, "마이크론": 25, "CXMT": 3}),
    ("2025 Q2", {"삼성전자": 33, "SK하이닉스": 39, "마이크론": 22, "CXMT": 4}),
    ("2025 Q3", {"삼성전자": 33, "SK하이닉스": 33, "마이크론": 26, "CXMT": 6}),
    ("2025 Q4", {"삼성전자": 36, "SK하이닉스": 32, "마이크론": 22, "CXMT": 8}),
    ("2026 Q1", {"삼성전자": 38, "SK하이닉스": 29, "마이크론": 22, "CXMT": 8}),
    ("2026 Q2", {"삼성전자": 39, "SK하이닉스": 26, "마이크론": 25}),
]


def build() -> dict:
    rows = []
    for label, shares in DRAM_QUARTERS:
        known = sum(shares.values())
        row = {"q": label}
        for v in VENDORS:
            row[v] = shares.get(v)
        row["기타"] = max(0, round(100 - known, 1))
        rows.append(row)
    return {
        "source": SOURCE,
        "vendors": VENDORS,
        "dram": rows,
    }
