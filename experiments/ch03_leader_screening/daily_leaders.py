"""3장 — 일 단위로 본 주도주: 거래대금 집중도, 순위 지속성, 다음 날 움직임.

장중 탐색(03-2, 03-3)에 앞서, 장 마감 후 확정된 일별 데이터로 "주도주 후보"가
어떤 성질을 갖는지 본다. API를 호출하지 않는다(krx_backfill.py 결과 사용).

다음 날 움직임은 매매 전략의 수익이 아니라 묘사 통계다. 거래비용을 넣지 않았다.

사용:
    uv run python experiments/ch03_leader_screening/daily_leaders.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from abcd.screener.universe import load_range  # noqa: E402

KRX = ROOT / "data" / "krx"
TOP = 30


def index_returns() -> pd.DataFrame:
    rows = []
    for name, idx_name, mkt in (("kospi_index", "코스피", "KOSPI"), ("kosdaq_index", "코스닥", "KOSDAQ")):
        for p in sorted((KRX / name).glob("*.parquet")):
            d = pd.read_parquet(p)
            d = d[d["IDX_NM"] == idx_name]   # "(외국주포함)" 행은 종가가 비어 있다(2장 함정)
            if len(d):
                rows.append({"day": p.stem, "market": mkt, "idx_chg": float(d["FLUC_RT"].iloc[0])})
    return pd.DataFrame(rows)


def describe(g: pd.DataFrame) -> dict:
    return {
        "n": len(g),
        "gap_mean": round(g["n_gap"].mean(), 2), "gap_median": round(g["n_gap"].median(), 2),
        "open_to_high_median": round(g["n_o2h"].median(), 2),
        "p_open_to_high_ge3": round((g["n_o2h"] >= 3).mean(), 3),
        "open_to_close_mean": round(g["n_o2c"].mean(), 2), "open_to_close_median": round(g["n_o2c"].median(), 2),
        "p_open_to_close_pos": round((g["n_o2c"] > 0).mean(), 3),
        "open_to_low_median": round(g["n_o2l"].median(), 2),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    u = load_range(KRX)
    u = u.merge(index_returns(), on=["day", "market"], how="left")
    u["rs"] = u["chg_pct"] - u["idx_chg"]                       # 시장 대비 상대강도(%p)
    u["value_rank"] = u.groupby("day")["value"].rank(ascending=False, method="first")
    days = sorted(u["day"].unique())
    res: dict = {"measured_at": datetime.now().isoformat(timespec="seconds"),
                 "days": len(days), "first_day": days[0], "last_day": days[-1], "top": TOP}

    # 1) 유니버스 크기와 거래대금 집중도
    per_day = u.groupby("day").agg(n=("code", "size"), total=("value", "sum"))
    share = {}
    for k in (10, 30, 50, 100):
        topk = u[u["value_rank"] <= k].groupby("day")["value"].sum() / per_day["total"]
        share[f"top{k}"] = round(float(topk.median()), 3)
    res["universe_size_median"] = int(per_day["n"].median())
    res["value_share_median"] = share

    # 2) 순위 지속성: 오늘 거래대금 상위 TOP 중 내일도 상위 TOP에 남는 비율
    tops = u[u["value_rank"] <= TOP].groupby("day")["code"].apply(set)
    stay = [len(tops[a] & tops[b]) / TOP for a, b in zip(days, days[1:])]
    res["top_stay_next_day_mean"] = round(sum(stay) / len(stay), 3)
    yearly = u[u["value_rank"] <= TOP].groupby("code").size()
    res["distinct_codes_in_top"] = int(yearly.size)
    res["codes_in_top_ge_50days"] = int((yearly >= 50).sum())

    # 3) 다음 날 움직임 (%): 갭, 시가→고가, 시가→종가, 시가→저가
    nxt = u[["day", "code", "open", "high", "low", "close"]].copy()
    nxt["day"] = nxt["day"].map(dict(zip(days[1:], days[:-1])))   # 다음 거래일 값을 전날 행에 붙인다
    m = u.merge(nxt.dropna(subset=["day"]), on=["day", "code"], suffixes=("", "_n"))
    m = m[(m["open_n"] > 0)]
    m["n_gap"] = (m["open_n"] / m["close"] - 1) * 100
    m["n_o2h"] = (m["high_n"] / m["open_n"] - 1) * 100
    m["n_o2c"] = (m["close_n"] / m["open_n"] - 1) * 100
    m["n_o2l"] = (m["low_n"] / m["open_n"] - 1) * 100
    groups = {
        "전체 대상 종목": m,
        f"거래대금 상위 {TOP}": m[m["value_rank"] <= TOP],
        "등락률 +10% 이상": m[m["chg_pct"] >= 10],
        f"주도주 후보(상위 {TOP} & +10% 이상 & 상대강도>0)": m[(m["value_rank"] <= TOP) & (m["chg_pct"] >= 10) & (m["rs"] > 0)],
        f"상위 {TOP} & 하락": m[(m["value_rank"] <= TOP) & (m["chg_pct"] < 0)],
        "상한가(+29.5% 이상)": m[m["chg_pct"] >= 29.5],
    }
    res["next_day"] = {k: describe(g) for k, g in groups.items()}

    print(json.dumps(res, ensure_ascii=False, indent=1))
    out = ROOT / "reports" / "ch03" / "daily_leaders.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    u.to_parquet(ROOT / "data" / "krx" / "universe_daily.parquet", index=False)
    print(f"[저장] {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
