"""3장 — 장중 순위 스냅샷. 키움 순위 API는 과거 시점 순위를 주지 않으므로 직접 쌓는다.

정기 작업(거래일 09:00~15:30, 10분 간격)으로 실행한다.
저장: data/rank/<YYYYMMDD>/<HHMM>_<TR>.json (응답 원문 목록, 첫 페이지)
장 시간 밖이면 아무것도 하지 않고 끝난다.

사용:
    uv run python experiments/ch03_leader_screening/rank_snapshot.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from abcd.broker.kiwoom import KiwoomClient  # noqa: E402
from rank_probe import RANKS  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    now = datetime.now()
    if now.weekday() >= 5 or not ("0900" <= now.strftime("%H%M") <= "1535"):
        print("장 시간 아님 — 종료")
        return
    c = KiwoomClient()
    out_dir = ROOT / "data" / "rank" / now.strftime("%Y%m%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    for api, (name, body) in RANKS.items():
        j, h = c.post("/api/dostk/rkinfo", api, body)
        rows = next((v for v in j.values() if isinstance(v, list)), [])
        (out_dir / f"{now:%H%M}_{api}.json").write_text(
            json.dumps({"ts": now.isoformat(timespec="seconds"), "api": api, "name": name, "rows": rows},
                       ensure_ascii=False), encoding="utf-8")
        print(api, name, len(rows), flush=True)


if __name__ == "__main__":
    main()
