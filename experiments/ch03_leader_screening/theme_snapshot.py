"""3장 — 키움 테마 분류 스냅샷: 테마 목록(ka90001)과 테마별 구성 종목(ka90002).

키움 테마 API는 "지금의" 테마 구성만 준다. 과거 어느 날 어떤 테마에 속했는지는 알 수 없으므로
이 스냅샷을 과거 1년에 적용하면 사후 분류가 된다(03-2에서 한계로 다룬다).

저장: data/theme/<YYYYMMDD>/groups.json   (ka90001 원문 목록)
      data/theme/<YYYYMMDD>/members.parquet (thema_grp_cd, thema_nm, stk_cd, stk_nm)

사용:
    uv run python experiments/ch03_leader_screening/theme_snapshot.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from abcd.broker.kiwoom import KiwoomClient  # noqa: E402

PATH = "/api/dostk/thme"


def groups(c: KiwoomClient) -> list[dict]:
    body = {"qry_tp": "0", "stk_cd": "", "date_tp": "10", "thema_nm": "", "flu_pl_amt_tp": "1", "stex_tp": "1"}
    rows, cont, key = [], "", ""
    while True:
        j, h = c.post(PATH, "ka90001", body, cont_yn=cont, next_key=key)
        rows.extend(j.get("thema_grp") or [])
        cont, key = h.get("cont-yn", "N"), h.get("next-key", "")
        if cont != "Y":
            return rows


def members(c: KiwoomClient, grp_cd: str) -> list[dict]:
    body = {"date_tp": "1", "thema_grp_cd": grp_cd, "stex_tp": "1"}
    rows, cont, key = [], "", ""
    while True:
        j, h = c.post(PATH, "ka90002", body, cont_yn=cont, next_key=key)
        rows.extend(j.get("thema_comp_stk") or [])
        cont, key = h.get("cont-yn", "N"), h.get("next-key", "")
        if cont != "Y":
            return rows


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    c = KiwoomClient()
    out = ROOT / "data" / "theme" / datetime.now().strftime("%Y%m%d")
    out.mkdir(parents=True, exist_ok=True)
    g = groups(c)
    (out / "groups.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    print(f"테마 {len(g)}개", flush=True)
    recs = []
    for i, grp in enumerate(g, 1):
        for s in members(c, grp["thema_grp_cd"]):
            recs.append({"thema_grp_cd": grp["thema_grp_cd"], "thema_nm": grp.get("thema_nm", ""),
                         "stk_cd": s.get("stk_cd", "")[:6], "stk_nm": s.get("stk_nm", "")})
        if i % 50 == 0:
            print(f"[{i}/{len(g)}] 구성 {len(recs)}건", flush=True)
    m = pd.DataFrame(recs)
    m.to_parquet(out / "members.parquet", index=False)
    print(json.dumps({"themes": len(g), "rows": len(m), "codes": int(m["stk_cd"].nunique()) if len(m) else 0,
                      "stat": c.stat.summary()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
