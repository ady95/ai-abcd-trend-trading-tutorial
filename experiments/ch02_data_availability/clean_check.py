"""2장 실측 — 수집한 1분봉을 표준 스키마로 정제하고 누락·거래량을 점검.

measure.py minute / daily 로 받은 원본(data/raw)을 사용합니다. API를 호출하지 않습니다.
1) 정제 결과를 data/clean/minute1/KRX/<종목>.parquet 로 저장
2) 날짜별 연속매매 봉 수·빈 분 (gap_report)
3) DuckDB로 1분봉 일합계 거래량과 일봉(ka10081) 거래량 대조

사용:
    uv run python experiments/ch02_data_availability/clean_check.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from abcd.collector.minute_bars import REGULAR_BARS, gap_report, normalize, save  # noqa: E402

RAW, CLEAN = ROOT / "data" / "raw", ROOT / "data" / "clean" / "minute1"
CODES = ["005930", "000660", "247540", "035720"]
COLLECTED_ON = date(2026, 11, 5)  # 원본을 받은 날


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    result = {"measured_at": datetime.now().isoformat(timespec="seconds"), "stocks": []}
    for code in CODES:
        raw = pd.read_parquet(RAW / "ka10080_tic1" / f"{code}.parquet")
        bars = normalize(raw.to_dict("records"), code, collected_on=COLLECTED_ON)
        save(bars, CLEAN)
        rep = gap_report(bars)
        short = rep[rep["regular_bars"] < REGULAR_BARS]
        r = {"code": code, "bars": len(bars), "days": len(rep),
             "days_full_regular": int((rep["regular_bars"] == REGULAR_BARS).sum()),
             "days_short": short.reset_index().astype(str).to_dict("records")[:10],
             "missing_inside_total": int(rep["missing_inside"].sum())}
        print(json.dumps(r, ensure_ascii=False), flush=True)
        result["stocks"].append(r)

    # 1분봉 일합계 vs 일봉 거래량 — DuckDB가 parquet 파일을 바로 읽는다
    con = duckdb.connect()
    daily = pd.concat([pd.read_parquet(RAW / "ka10081" / f"{c}.parquet").assign(code=c) for c in CODES])
    daily = daily.assign(day=pd.to_datetime(daily["dt"]).dt.date,
                         d_volume=pd.to_numeric(daily["trde_qty"]).astype("int64"))[["code", "day", "d_volume"]]
    con.register("daily", daily)
    cmp = con.sql(f"""
        WITH m AS (
            SELECT code, CAST(ts AS DATE) AS day, SUM(volume) AS m_volume
            FROM read_parquet('{(CLEAN / 'KRX' / '*.parquet').as_posix()}')
            GROUP BY ALL
        )
        SELECT m.code, COUNT(*) AS days,
               SUM(CASE WHEN m_volume = d_volume THEN 1 ELSE 0 END) AS same_days,
               ROUND(AVG((d_volume - m_volume) * 100.0 / d_volume), 3) AS avg_gap_pct,
               MAX(d_volume - m_volume) AS max_gap
        FROM m JOIN daily d USING (code, day)
        GROUP BY m.code ORDER BY m.code
    """).df()
    print(cmp.to_string(index=False))
    result["minute_sum_vs_daily"] = cmp.astype({"days": int, "same_days": int, "max_gap": int}).to_dict("records")
    out = ROOT / "reports" / "ch02" / "clean_check.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"[저장] {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
