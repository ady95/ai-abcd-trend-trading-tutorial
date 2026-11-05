"""3장 실측 — 키움 순위 API 4종을 한 번씩 호출해 응답 구조를 기록한다.

순위 API는 "지금 이 순간"의 순위만 준다(과거 시점 조회 없음). 장중에 여러 번 실행하면
시점별 스냅샷이 쌓인다. 결과: reports/ch03/rank_probe_<YYYYMMDD_HHMM>.json

사용:
    uv run python experiments/ch03_leader_screening/rank_probe.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from abcd.broker.kiwoom import KiwoomClient  # noqa: E402

# mrkt_tp: 000 전체 / 001 코스피 / 101 코스닥, stex_tp: 1 KRX / 2 NXT / 3 통합
RANKS = {
    "ka10032": ("거래대금상위", {"mrkt_tp": "000", "mang_stk_incls": "0", "stex_tp": "1"}),
    "ka10027": ("전일대비등락률상위", {"mrkt_tp": "000", "sort_tp": "1", "trde_qty_cnd": "0000", "stk_cnd": "0",
                                  "crd_cnd": "0", "updown_incls": "1", "pric_cnd": "0", "trde_prica_cnd": "0",
                                  "stex_tp": "1"}),
    "ka10030": ("당일거래량상위", {"mrkt_tp": "000", "sort_tp": "1", "mang_stk_incls": "0", "crd_tp": "0",
                              "trde_qty_tp": "0", "pric_tp": "0", "trde_prica_tp": "0", "mrkt_open_tp": "0",
                              "stex_tp": "1"}),
    "ka10023": ("거래량급증", {"mrkt_tp": "000", "sort_tp": "1", "tm_tp": "2", "trde_qty_tp": "5", "tm": "",
                           "stk_cnd": "0", "pric_tp": "0", "stex_tp": "1"}),
}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    c = KiwoomClient()
    now = datetime.now()
    out = {"measured_at": now.isoformat(timespec="seconds"), "mode": c.mode, "results": {}}
    for api, (name, body) in RANKS.items():
        j, h = c.post("/api/dostk/rkinfo", api, body)
        key, rows = next(((k, v) for k, v in j.items() if isinstance(v, list)), (None, []))
        codes = [r.get("stk_cd", "") for r in rows]
        r = {"name": name, "body": body, "list_key": key, "rows_first_page": len(rows),
             "cont_yn": h.get("cont-yn"), "fields": list(rows[0].keys()) if rows else [],
             "non_numeric_codes": [x for x in codes if not x.isdigit()][:10],
             "top5": [(x.get("stk_cd"), x.get("stk_nm")) for x in rows[:5]],
             "rows": rows}
        print(api, name, key, len(rows), h.get("cont-yn"), r["top5"], flush=True)
        out["results"][api] = r
    p = ROOT / "reports" / "ch03" / f"rank_probe_{now:%Y%m%d_%H%M}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[저장] {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
