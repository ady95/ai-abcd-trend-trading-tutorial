"""3장 — KRX 전 종목 일별 시세·종목 기본정보·지수를 날짜별로 내려받는다.

data/krx/<이름>/<YYYYMMDD>.parquet 로 저장하고, 이미 받은 날짜는 건너뛴다(이어받기).
주말은 호출하지 않고, 평일 휴장일은 빈 응답으로 판정해 data/krx/holidays.txt 에 적는다.

사용:
    uv run python experiments/ch03_leader_screening/krx_backfill.py 20251001 20261105
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from abcd.collector.krx import ENDPOINTS, KrxClient  # noqa: E402

OUT = ROOT / "data" / "krx"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    start, end = (datetime.strptime(x, "%Y%m%d") for x in sys.argv[1:3])
    c = KrxClient()
    OUT.mkdir(parents=True, exist_ok=True)
    holidays = OUT / "holidays.txt"
    known_holidays = set(holidays.read_text().split()) if holidays.exists() else set()
    day, n_days = start, 0
    while day <= end:
        d = day.strftime("%Y%m%d")
        day += timedelta(days=1)
        if datetime.strptime(d, "%Y%m%d").weekday() >= 5 or d in known_holidays:
            continue
        if (OUT / "kospi_daily" / f"{d}.parquet").exists():
            continue
        first = c.get("kospi_daily", d)
        if first.empty and (datetime.now() - datetime.strptime(d, "%Y%m%d")).days < 3:
            # KRX는 거래일 데이터를 다음 날 이후에 공개한다. 최근 날짜의 빈 응답은 휴장이 아니라 미공개.
            print(d, "아직 공개 전 (휴장으로 기록하지 않음)", flush=True)
            continue
        if first.empty:  # 평일 휴장일
            known_holidays.add(d)
            holidays.write_text("\n".join(sorted(known_holidays)))
            print(d, "휴장", flush=True)
            continue
        frames = {"kospi_daily": first, **{name: c.get(name, d) for name in ENDPOINTS if name != "kospi_daily"}}
        for name, df in frames.items():
            p = OUT / name / f"{d}.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(p, index=False)
        n_days += 1
        if n_days % 20 == 0:
            print(d, f"{n_days}거래일, 호출 {c.calls}", flush=True)
    print(f"완료: 새로 받은 거래일 {n_days}, 호출 {c.calls}, 휴장일 {len(known_holidays)}")


if __name__ == "__main__":
    main()
