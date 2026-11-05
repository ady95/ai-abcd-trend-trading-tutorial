"""키움 1분봉 정제 — 원본 응답(문자열) → 연구용 표준 스키마.

2장 실측에서 확인한 규칙을 코드로 고정합니다.
- 가격 문자열에는 등락 부호가 붙어 올 수 있다 ("-201500") → 절대값
- 봉 시각은 그 1분 구간의 시작 시각이다 (09:00 봉 = 09:00:00~09:00:59)
- 체결이 없는 분은 봉이 없다 → 봉 개수가 아니라 시각으로 다룬다
- 수정주가는 과거 전체에 소급 적용된다 → 언제 받은 데이터인지(collected_on)를 함께 저장
- NXT 미거래 종목은 빈 문자열 행 1개가 온다 → 시각이 빈 행은 버린다
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

# 표준 스키마: 열 이름과 자료형
SCHEMA = {
    "ts": "datetime64[ns]",   # 봉 시작 시각 (한국 시간, 시간대 정보 없음)
    "code": "string",         # 종목코드 6자리
    "venue": "string",        # KRX / NXT / AL(통합)
    "open": "int64", "high": "int64", "low": "int64", "close": "int64",
    "volume": "int64",
    "adjusted": "bool",       # 수정주가 여부
    "collected_on": "string", # 수집일 YYYY-MM-DD — 수정주가가 바뀌면 이 날짜로 구분
}

# 세션 구분 (KRX, 2026-11 실측)
#   regular      09:00~15:19  연속매매 (하루 380봉)
#   close        15:20~15:39  종가 단일가·장후 시간외 종가 (15:30, 15:35 봉 등)
#   after        15:40~19:59  2026-09-14 도입 애프터마켓 구간 (16:00~19:59 봉)
REGULAR_FIRST, REGULAR_LAST = "0900", "1519"
REGULAR_BARS = 380


def normalize(rows: list[dict], code: str, venue: str = "KRX", adjusted: bool = True,
              collected_on: date | None = None) -> pd.DataFrame:
    """ka10080 응답 행 목록 → 표준 스키마 DataFrame (시각 오름차순, 중복 제거)."""
    df = pd.DataFrame(rows)
    if df.empty or "cntr_tm" not in df:
        return pd.DataFrame({k: pd.Series(dtype=v) for k, v in SCHEMA.items()})
    df = df[df["cntr_tm"].fillna("") != ""]

    def num(col: str) -> pd.Series:
        return pd.to_numeric(df[col], errors="coerce").abs().astype("int64")

    out = pd.DataFrame({
        "ts": pd.to_datetime(df["cntr_tm"], format="%Y%m%d%H%M%S"),
        "code": code[:6],
        "venue": venue,
        "open": num("open_pric"), "high": num("high_pric"), "low": num("low_pric"),
        "close": num("cur_prc"), "volume": num("trde_qty"),
        "adjusted": adjusted,
        "collected_on": (collected_on or date.today()).isoformat(),
    }).astype(SCHEMA)
    # 연속조회 페이지 경계에서 같은 봉이 두 번 올 수 있다 → 마지막 것만 남긴다
    return out.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)


def session(ts: pd.Series) -> pd.Series:
    """봉 시각 → regular / close / after / pre."""
    hm = ts.dt.strftime("%H%M")
    return pd.Series(pd.cut(hm.astype(int), [-1, 859, 1519, 1539, 2400],
                            labels=["pre", "regular", "close", "after"]), index=ts.index).astype("string")


def gap_report(bars: pd.DataFrame) -> pd.DataFrame:
    """날짜별 연속매매(09:00~15:19) 봉 수와 빈 분 수.

    first_regular가 09:00보다 늦으면 개장 지연일(예: 수능일 10:00 개장)일 수 있으므로
    빈 분은 첫 봉 이후만 센다. 같은 날 여러 종목이 함께 늦으면 시장 일정, 한 종목만이면 거래정지·무거래.
    """
    reg = bars[session(bars["ts"]) == "regular"]
    g = reg.groupby(reg["ts"].dt.date)["ts"]
    rep = pd.DataFrame({
        "regular_bars": g.size(),
        "first_regular": g.min().dt.strftime("%H:%M"),
        "last_regular": g.max().dt.strftime("%H:%M"),
    })
    span = (g.max() - g.min()).dt.total_seconds() // 60 + 1
    rep["missing_inside"] = (span - rep["regular_bars"]).astype(int)
    rep.index.name = "day"
    return rep


def save(bars: pd.DataFrame, root: Path) -> Path:
    """root/<venue>/<code>.parquet 로 저장 (종목별 파일 하나)."""
    code, venue = bars["code"].iloc[0], bars["venue"].iloc[0]
    path = Path(root) / venue / f"{code}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(path, index=False)
    return path
