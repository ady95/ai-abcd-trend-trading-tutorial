"""3장 — 주도주 후보 종목의 1분봉(KRX, 수정주가)을 끝까지 내려받아 정제 저장한다.

대상: reports/ch03/minute_targets.txt (한 줄에 종목코드 하나, make_targets 로 생성)
저장: data/raw/ka10080_tic1/<코드>.parquet (원본 문자열)
      data/clean/minute1/KRX/<코드>.parquet (2장 표준 스키마)
이미 오늘 받은 종목은 건너뛴다 → 중단돼도 다시 실행하면 이어서 받는다.

사용:
    uv run python experiments/ch03_leader_screening/minute_backfill.py make_targets 50
    uv run python experiments/ch03_leader_screening/minute_backfill.py run
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from abcd.broker.kiwoom import KiwoomClient, KiwoomError  # noqa: E402
from abcd.collector.minute_bars import normalize, save  # noqa: E402

TARGETS = ROOT / "reports" / "ch03" / "minute_targets.txt"
RAW = ROOT / "data" / "raw" / "ka10080_tic1"
CLEAN = ROOT / "data" / "clean" / "minute1"


def make_targets(top: int) -> None:
    """키움 1분봉 제공 기간(2025-11-03~) 동안 일별 거래대금 상위 top 에 한 번이라도 든 종목."""
    u = pd.read_parquet(ROOT / "data" / "krx" / "universe_daily.parquet")
    u = u[(u["day"] >= "20251103") & (u["value_rank"] <= top)]
    order = u.groupby("code").size().sort_values(ascending=False)   # 자주 든 종목부터 받는다
    TARGETS.parent.mkdir(parents=True, exist_ok=True)
    TARGETS.write_text("\n".join(order.index) + "\n", encoding="utf-8")
    print(f"{len(order)}종목 → {TARGETS.relative_to(ROOT)}")


def run() -> None:
    codes = TARGETS.read_text(encoding="utf-8").split()
    c = KiwoomClient()
    today = date.today()
    done = failed = skipped = 0
    t_start = time.monotonic()
    log = []
    for i, code in enumerate(codes, 1):
        clean_path = CLEAN / "KRX" / f"{code}.parquet"
        if clean_path.exists():
            prev = pd.read_parquet(clean_path, columns=["collected_on"])
            # 하루 전까지 받은 종목은 건너뛴다 (자정을 넘겨 실행이 이어져도 다시 받지 않도록)
            if len(prev) and prev["collected_on"].iloc[0] >= (today - timedelta(days=1)).isoformat():
                skipped += 1
                continue
        t0 = time.monotonic()
        try:
            rows = []
            for page in c.iter_pages(c.minute_chart, code):
                rows.extend(page)
        except KiwoomError as e:
            failed += 1
            log.append({"code": code, "error": str(e)[:200]})
            print(f"[{i}/{len(codes)}] {code} 실패: {e}", flush=True)
            continue
        raw = pd.DataFrame(rows)
        RAW.mkdir(parents=True, exist_ok=True)
        raw.to_parquet(RAW / f"{code}.parquet", index=False)
        bars = normalize(rows, code, collected_on=today)
        if len(bars):
            save(bars, CLEAN)
        done += 1
        r = {"code": code, "bars": len(bars), "first": str(bars["ts"].min()) if len(bars) else None,
             "seconds": round(time.monotonic() - t0, 1)}
        log.append(r)
        elapsed = time.monotonic() - t_start
        eta = elapsed / done * (len(codes) - i) / 3600
        print(f"[{i}/{len(codes)}] {code} {r['bars']}봉 {r['first']} {r['seconds']}초 · 남은 예상 {eta:.1f}시간",
              flush=True)
    summary = {"finished_at": datetime.now().isoformat(timespec="seconds"), "targets": len(codes),
               "done": done, "skipped": skipped, "failed": failed,
               "hours": round((time.monotonic() - t_start) / 3600, 2), "stat": c.stat.summary(), "log": log}
    out = ROOT / "reports" / "ch03" / f"minute_backfill_{today:%Y%m%d}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "log"}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "make_targets":
        make_targets(int(sys.argv[2]))
    else:
        run()
