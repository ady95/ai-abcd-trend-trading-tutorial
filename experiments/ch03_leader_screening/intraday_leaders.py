"""3장 — 장중에 주도주를 얼마나 일찍, 얼마나 정확히 알아볼 수 있는가.

장 초반 시점 T(09:10, 09:30, 10:00)에 그때까지의 1분봉만 보고 후보를 고른 뒤
1) 그 후보가 장 마감 후 확정된 거래대금 상위 30과 얼마나 겹치는지 (조기 식별)
2) 후보가 T 이후 장 마감까지 어떻게 움직였는지 (사후 움직임, 묘사 통계)
3) 시간대 보정 거래량(RVOL)이 사후 움직임과 관계가 있는지
4) 강한 테마 안의 대장주(거래대금 1위)가 추종주와 다르게 움직이는지
를 본다. API를 호출하지 않는다(minute_backfill.py, daily_leaders.py 결과 사용).

주의
- 사후 움직임은 거래비용을 넣지 않은 묘사 통계이며 매매 전략의 수익이 아니다.
- 대상은 "1년 중 한 번이라도 일별 거래대금 상위 50에 든 종목"이다. 이 목록 자체가
  사후 정보로 만들어졌으므로, 이 집합 안의 평균 움직임을 시장 전체로 일반화하지 않는다.
  장 마감 상위 30은 항상 이 집합 안에 있으므로 1)의 재현율은 이 편향의 영향을 받지 않는다.
- 분봉 거래대금은 종가×거래량 근사다(키움 분봉에는 거래대금 필드가 없다).

사용:
    uv run python experiments/ch03_leader_screening/intraday_leaders.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CLEAN = ROOT / "data" / "clean" / "minute1" / "KRX"
UNIVERSE = ROOT / "data" / "krx" / "universe_daily.parquet"
CHECKPOINTS = (910, 930, 1000)   # 시점 T: 이 시각 "이전"에 시작한 봉만 본다 (09:10 → 09:00~09:09 봉)
TOP = 30
UPPER_LIMIT = 29.5               # 이 이상 오른 종목은 T 시점에 살 수 없으므로 사후 움직임에서 뺀다
RVOL_DAYS = 20
THEME = ROOT / "data" / "theme"
MIN_MEMBERS = 3                  # 시점 T에 대상 종목 안에서 구성 종목이 이 수 이상인 테마만
HOT_THEMES = 5


def per_code(path: Path, prev_day: dict[str, str]) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=["ts", "high", "low", "close", "volume"])
    hm = df["ts"].dt.hour * 100 + df["ts"].dt.minute
    df = df[(hm >= 900) & (hm <= 1530)].copy()          # 정규장 + 15:30 종가 단일가 봉
    if df.empty:
        return pd.DataFrame()
    df["hm"] = hm[df.index]
    df["day"] = df["ts"].dt.strftime("%Y%m%d")
    df["val"] = df["close"] * df["volume"]
    day = df.groupby("day").agg(day_close=("close", "last"), day_val=("val", "sum"))
    out = []
    for t in CHECKPOINTS:
        pre = df[df["hm"] < t].groupby("day").agg(
            cum_val=("val", "sum"), cum_vol=("volume", "sum"), price=("close", "last"), first_hm=("hm", "min"))
        post = df[(df["hm"] >= t) & (df["hm"] <= 1519)].groupby("day").agg(pmax=("high", "max"), pmin=("low", "min"))
        g = pre.join(post).join(day)
        # 같은 시점 T까지의 누적 거래량을 과거 20거래일 평균과 비교 (그날 이전 값만 사용)
        g["rvol"] = g["cum_vol"] / g["cum_vol"].rolling(RVOL_DAYS, min_periods=10).mean().shift(1)
        g["prev_close"] = g.index.map(prev_day).map(day["day_close"])
        g["t"] = t
        out.append(g.reset_index())
    r = pd.concat(out)
    r["code"] = path.stem
    return r


def stats(g: pd.DataFrame) -> dict:
    return {
        "n": int(len(g)),
        "post_median": round(float(g["post"].median()), 2), "post_mean": round(float(g["post"].mean()), 2),
        "p_post_pos": round(float((g["post"] > 0).mean()), 3),
        "post_max_median": round(float(g["post_max"].median()), 2),
        "post_min_median": round(float(g["post_min"].median()), 2),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    u = pd.read_parquet(UNIVERSE, columns=["day", "code", "value", "value_rank"])
    days = sorted(u["day"].unique())
    prev_day = dict(zip(days[1:], days[:-1]))
    files = sorted(CLEAN.glob("*.parquet"))
    m = pd.concat([per_code(p, prev_day) for p in files], ignore_index=True)
    # KRX 일별 자료가 확정된 날만 쓴다. 첫날(2025-11-03)은 전일 종가가 없고,
    # 수집하던 날의 장중 봉은 아직 끝나지 않은 하루다.
    m = m[m["day"].isin(days) & (m["day"] >= "20251104")]

    # 개장이 09:00이 아닌 날(수능일 등)은 시점 T의 의미가 달라지므로 뺀다
    first = m.groupby("day")["first_hm"].min()
    late = sorted(set(d for d in days if d >= m["day"].min()) - set(first[first <= 900].index))
    m = m[~m["day"].isin(late)]

    m["chg"] = (m["price"] / m["prev_close"] - 1) * 100
    m["proxy"] = m.groupby(["day", "t"])["chg"].transform("median")   # 대상 종목 등락률 중앙값 = 시장 대용
    m["rs"] = m["chg"] - m["proxy"]
    m["rank_t"] = m.groupby(["day", "t"])["cum_val"].rank(ascending=False, method="first")
    m["post"] = (m["day_close"] / m["price"] - 1) * 100
    m["post_max"] = (m["pmax"] / m["price"] - 1) * 100
    m["post_min"] = (m["pmin"] / m["price"] - 1) * 100

    res: dict = {"measured_at": datetime.now().isoformat(timespec="seconds"), "codes": len(files),
                 "days": int(m["day"].nunique()), "first_day": m["day"].min(), "last_day": m["day"].max(),
                 "excluded_late_open_days": late, "top": TOP}

    # 0) 분봉 거래대금 근사(종가×거래량)가 KRX 일별 거래대금과 얼마나 맞는가 (최근 60거래일)
    recent = days[-60:]
    chk = m[(m["t"] == CHECKPOINTS[0]) & m["day"].isin(recent)].merge(u, on=["day", "code"])
    ratio = chk["day_val"] / chk["value"]
    res["value_approx_ratio"] = {"n": int(len(ratio)), "median": round(float(ratio.median()), 4),
                                 "p10": round(float(ratio.quantile(0.1)), 4), "p90": round(float(ratio.quantile(0.9)), 4)}

    # 1) 조기 식별: 시점 T의 누적 거래대금 상위 30이 장 마감 상위 30과 몇 개 겹치나
    final = u[u["value_rank"] <= TOP].groupby("day")["code"].apply(set)
    ident = {}
    for t, g in m.groupby("t"):
        top_t = g[g["rank_t"] <= TOP].groupby("day")["code"].apply(set)
        hit = [len(top_t[d] & final[d]) / TOP for d in top_t.index if d in final.index]
        ident[str(t)] = round(sum(hit) / len(hit), 3)
    # 비교 기준: 전날 장 마감 상위 30을 그대로 쓰는 경우
    fdays = list(final.index)
    base = [len(final[b] & final[a]) / TOP for a, b in zip(fdays, fdays[1:]) if b in set(m["day"])]
    ident["prev_day_top"] = round(sum(base) / len(base), 3)
    res["identification_recall"] = ident

    # 2) 사후 움직임: T 가격 → 장 마감, T 이후 최고·최저 (%)
    buyable = m[(m["chg"] < UPPER_LIMIT) & m["price"].gt(0) & m["prev_close"].notna()]
    res["excluded_upper_limit_at_t"] = int(((m["chg"] >= UPPER_LIMIT)).sum())
    post = {}
    for t, g in buyable.groupby("t"):
        top = g["rank_t"] <= TOP
        groups = {
            "대상 전체": g,
            f"누적 거래대금 상위 {TOP}": g[top],
            f"상위 {TOP} & 상대강도>0": g[top & (g["rs"] > 0)],
            f"상위 {TOP} & 상대강도>0 & +10% 이상": g[top & (g["rs"] > 0) & (g["chg"] >= 10)],
            f"상위 {TOP} & 상대강도<0": g[top & (g["rs"] < 0)],
        }
        post[str(t)] = {k: stats(v) for k, v in groups.items()}
    res["post_move"] = post

    # 2-1) 재현성: 기간을 반으로 나눠 같은 방향인지
    half = sorted(buyable["day"].unique())
    mid = half[len(half) // 2]
    split = {}
    for t, g in buyable.groupby("t"):
        sel = g[(g["rank_t"] <= TOP) & (g["rs"] > 0)]
        split[str(t)] = {"후보 전반": stats(sel[sel["day"] < mid]), "후보 후반": stats(sel[sel["day"] >= mid]),
                         "대상 전체 전반": stats(g[g["day"] < mid]), "대상 전체 후반": stats(g[g["day"] >= mid])}
    res["post_move_halves"] = {"split_day": mid, **split}

    # 3) 시간대 보정 거래량(RVOL): 상대강도>0 종목을 RVOL 구간으로 나눠 사후 움직임 비교
    rv = {}
    bins = [0, 1, 2, 5, float("inf")]
    labels = ["<1", "1~2", "2~5", ">=5"]
    for t, g in buyable[buyable["rvol"].notna() & (buyable["rs"] > 0)].groupby("t"):
        b = pd.cut(g["rvol"], bins, labels=labels, right=False)
        rv[str(t)] = {lab: stats(g[b == lab]) for lab in labels}
        top30 = g[g["rank_t"] <= TOP]
        rv[str(t)]["상위 30 중 RVOL>=2"] = stats(top30[top30["rvol"] >= 2])
        rv[str(t)]["상위 30 중 RVOL<2"] = stats(top30[top30["rvol"] < 2])
    res["rvol"] = rv

    # 4) 테마 주도력: 시점 T에 테마 구성 종목의 상대강도 중앙값으로 테마를 줄 세우고,
    #    상위 테마 안에서 누적 거래대금 1위(대장)와 나머지(추종)를 비교한다.
    #    테마 구성은 수집일 현재 스냅샷이다(과거 날짜에 적용하면 사후 분류).
    snaps = sorted(THEME.glob("*/members.parquet"))
    if snaps:
        th = pd.read_parquet(snaps[-1], columns=["thema_grp_cd", "thema_nm", "stk_cd"]).rename(columns={"stk_cd": "code"})
        th = th.drop_duplicates()
        codes = set(m["code"])
        final_codes = set().union(*final.values)
        theme_res: dict = {"snapshot": snaps[-1].parent.name, "themes": int(th["thema_grp_cd"].nunique()),
                           "universe_codes_with_theme": round(len(codes & set(th["code"])) / len(codes), 3),
                           "final_top_codes_with_theme": round(len(final_codes & set(th["code"])) / len(final_codes), 3)}
        x = buyable.merge(th, on="code")
        x["n_mem"] = x.groupby(["day", "t", "thema_grp_cd"])["code"].transform("size")
        x = x[x["n_mem"] >= MIN_MEMBERS]
        x["theme_rs"] = x.groupby(["day", "t", "thema_grp_cd"])["rs"].transform("median")
        x["theme_rank"] = x.groupby(["day", "t"])["theme_rs"].rank(ascending=False, method="dense")
        x["in_theme_rank"] = x.groupby(["day", "t", "thema_grp_cd"])["cum_val"].rank(ascending=False, method="first")
        per_t = {}
        for t, g in x.groupby("t"):
            hot = g[g["theme_rank"] <= HOT_THEMES]
            lead = hot[hot["in_theme_rank"] == 1].drop_duplicates(["day", "code"])
            foll = hot[hot["in_theme_rank"] > 1].drop_duplicates(["day", "code"])
            foll = foll[~foll.set_index(["day", "code"]).index.isin(lead.set_index(["day", "code"]).index)]
            hot_keys = hot.set_index(["day", "code"]).index
            rest = g.drop_duplicates(["day", "code"])
            rest = rest[~rest.set_index(["day", "code"]).index.isin(hot_keys)]
            per_t[str(t)] = {f"상위 {HOT_THEMES}개 테마 대장": stats(lead),
                             f"상위 {HOT_THEMES}개 테마 추종": stats(foll),
                             "그 밖의 테마 종목": stats(rest)}
            # 테마 대장이 장 마감 상위 30에 드는 비율
            per_t[str(t)]["대장의 장 마감 상위 30 비율"] = round(float(
                lead.apply(lambda r: r["code"] in final.get(r["day"], set()), axis=1).mean()), 3)
        theme_res["by_t"] = per_t
        res["theme"] = theme_res

    print(json.dumps(res, ensure_ascii=False, indent=1))
    out = ROOT / "reports" / "ch03" / "intraday_leaders.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[저장] {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
