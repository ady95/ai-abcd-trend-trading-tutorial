"""2장 실측 — 키움 REST API 데이터 가용성 측정.

조회 API만 호출합니다(주문 없음). 결과 요약은 reports/ch02/<항목>.json,
원천 시세는 data/raw/ 아래 parquet으로 저장합니다(data/는 저장소에 커밋하지 않음).

사용 (저장소 루트에서):
    uv run python experiments/ch02_data_availability/measure.py token
    uv run python experiments/ch02_data_availability/measure.py minute   # 1분봉 전체 연속조회
    uv run python experiments/ch02_data_availability/measure.py minute5  # 5분봉 전체 연속조회
    uv run python experiments/ch02_data_availability/measure.py venue    # KRX/NXT/통합 비교
    uv run python experiments/ch02_data_availability/measure.py daily    # 일봉 범위·수정주가
    uv run python experiments/ch02_data_availability/measure.py rate     # 호출 처리율
    uv run python experiments/ch02_data_availability/measure.py all
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from abcd.broker.kiwoom import KiwoomClient, KiwoomError  # noqa: E402

REPORT_DIR = ROOT / "reports" / "ch02"
RAW_DIR = ROOT / "data" / "raw"
# 표본: 대표성 표본이 아니라 시장·NXT 거래 여부별 차이를 보기 위한 종목
SAMPLES = {
    "005930": "삼성전자 (KOSPI, NXT 거래)",
    "000660": "SK하이닉스 (KOSPI, NXT 거래)",
    "247540": "에코프로비엠 (KOSDAQ)",
    "035720": "카카오 (KOSPI)",
}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save(name: str, payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"measured_at": now(), "python": platform.python_version(), **payload}
    path = REPORT_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[저장] {path.relative_to(ROOT)}")


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:10]


# ---------------------------------------------------------------- 토큰
def m_token(c: KiwoomClient) -> None:
    """같은 앱키로 토큰을 연달아 받으면 같은 토큰이 오는가, 앞 토큰은 계속 유효한가."""
    a = c.issue_token()
    time.sleep(1)
    b = c.issue_token()
    # 앞 토큰(a)으로 직접 호출해 본다
    r = c.http.post("/api/dostk/stkinfo", json={"stk_cd": "005930"}, headers={
        "Content-Type": "application/json;charset=UTF-8", "authorization": f"Bearer {a['token']}", "api-id": "ka10001"})
    old = r.json()
    res = {
        "first": {"hash": h(a["token"]), "expires_dt": a["expires_dt"]},
        "second": {"hash": h(b["token"]), "expires_dt": b["expires_dt"]},
        "same_token": a["token"] == b["token"],
        "first_token_after_second_issue": {"return_code": old.get("return_code"), "return_msg": old.get("return_msg")},
    }
    print(json.dumps(res, ensure_ascii=False, indent=1))
    save("token", {"mode": c.mode, **res})


# ---------------------------------------------------------------- 분봉 연속조회
def backfill_minutes(c: KiwoomClient, code: str, tic: str) -> dict:
    t0, pages, rows = time.monotonic(), 0, []
    calls0, rl0 = c.stat.calls, c.stat.rate_limited
    for page in c.iter_pages(c.minute_chart, code, tic_scope=tic):
        pages += 1
        rows.extend(page)
        if pages % 20 == 0:
            print(f"  {code} tic={tic}: {pages}페이지, 마지막 {page[-1]['cntr_tm'] if page else '-'}", flush=True)
    df = pd.DataFrame(rows)
    out = RAW_DIR / f"ka10080_tic{tic}" / f"{code}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    days = df["cntr_tm"].str[:8]
    per_day = days.value_counts().sort_index()
    return {
        "code": code, "tic_scope": tic, "rows": len(df), "pages": pages,
        "first_bar": df["cntr_tm"].min(), "last_bar": df["cntr_tm"].max(),
        "trading_days": int(days.nunique()),
        "bars_per_day_mode": int(per_day.mode().iloc[0]),
        "bars_per_day_min": int(per_day.min()), "bars_per_day_max": int(per_day.max()),
        "first_day_bars": int(per_day.iloc[0]),
        "calls": c.stat.calls - calls0, "rate_limited": c.stat.rate_limited - rl0,
        "seconds": round(time.monotonic() - t0, 1),
        "columns": list(df.columns),
    }


def m_minute(c: KiwoomClient, tic: str = "1") -> None:
    results = []
    for code, name in SAMPLES.items():
        print(f"[{now()}] {code} {name} tic={tic} 연속조회 시작", flush=True)
        try:
            r = backfill_minutes(c, code, tic)
        except KiwoomError as e:
            r = {"code": code, "error": str(e)}
        r["name"] = name
        print(json.dumps(r, ensure_ascii=False), flush=True)
        results.append(r)
    save(f"minute_tic{tic}", {"mode": c.mode, "api": "ka10080", "adjusted": True,
                              "results": results, "stat": c.stat.summary()})


# ---------------------------------------------------------------- 거래소 구분
def m_venue(c: KiwoomClient) -> None:
    """KRX / NXT(_NX) / 통합(_AL) 1분봉 첫 페이지 비교 (최근 거래일 기준)."""
    results = []
    for code in SAMPLES:
        for suffix, venue in (("", "KRX"), ("_NX", "NXT"), ("_AL", "통합")):
            try:
                rows, cont, _ = c.minute_chart(code + suffix)
            except KiwoomError as e:
                results.append({"code": code, "venue": venue, "error": str(e)})
                continue
            df = pd.DataFrame(rows)
            r = {"code": code, "venue": venue, "rows_first_page": len(df), "cont_yn": cont}
            if len(df):
                last_day = df["cntr_tm"].str[:8].max()
                d = df[df["cntr_tm"].str[:8] == last_day]
                r.update({"last_day": last_day, "bars_last_day": len(d),
                          "first_time": d["cntr_tm"].min()[8:], "last_time": d["cntr_tm"].max()[8:],
                          "volume_last_day": int(d["trde_qty"].astype("int64").sum())})
            results.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
    save("venue", {"mode": c.mode, "api": "ka10080", "results": results, "stat": c.stat.summary()})


# ---------------------------------------------------------------- 일봉·수정주가
def m_daily(c: KiwoomClient) -> None:
    base = datetime.now().strftime("%Y%m%d")
    results = []
    for code, name in SAMPLES.items():
        frames = {}
        for adjusted in (True, False):
            rows = []
            pages = 0
            for page in c.iter_pages(c.daily_chart, code, base, adjusted=adjusted):
                rows.extend(page)
                pages += 1
            frames[adjusted] = pd.DataFrame(rows)
            if adjusted:
                out = RAW_DIR / "ka10081" / f"{code}.parquet"
                out.parent.mkdir(parents=True, exist_ok=True)
                frames[adjusted].to_parquet(out, index=False)
            print(f"  {code} adjusted={adjusted}: {len(rows)}행 {pages}페이지", flush=True)
        a, u = frames[True], frames[False]
        m = a.merge(u, on="dt", suffixes=("_adj", "_raw"))
        diff = m[m["cur_prc_adj"] != m["cur_prc_raw"]]
        r = {"code": code, "name": name, "rows": len(a), "first_day": a["dt"].min(), "last_day": a["dt"].max(),
             "columns": list(a.columns), "adjusted_vs_raw_diff_days": len(diff),
             "diff_last_day": diff["dt"].max() if len(diff) else None}
        print(json.dumps(r, ensure_ascii=False), flush=True)
        results.append(r)
    save("daily", {"mode": c.mode, "api": "ka10081", "results": results, "stat": c.stat.summary()})


# ---------------------------------------------------------------- 처리율
def m_rate(c: KiwoomClient) -> None:
    """간격 없이 순차 호출 40회 / 간격별 20회 — 제한 응답이 시작되는 지점."""
    results = []
    for interval in (0.0, 0.25, 0.4, 0.55):
        c.min_interval = interval
        ok = limited = 0
        t0 = time.monotonic()
        n = 40 if interval == 0 else 20
        for _ in range(n):
            c._wait()
            r = c.http.post("/api/dostk/stkinfo", json={"stk_cd": "005930"}, headers={
                "Content-Type": "application/json;charset=UTF-8", "authorization": f"Bearer {c.token()}",
                "api-id": "ka10001"})
            try:
                j = r.json()
            except ValueError:
                j = {}
            if r.status_code == 200 and j.get("return_code") == 0:
                ok += 1
            else:
                limited += 1
        sec = time.monotonic() - t0
        res = {"interval_s": interval, "calls": n, "ok": ok, "limited_or_error": limited,
               "seconds": round(sec, 1), "ok_per_s": round(ok / sec, 2)}
        print(json.dumps(res), flush=True)
        results.append(res)
        time.sleep(5)
    save("rate", {"mode": c.mode, "api": "ka10001", "results": results})


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("item", choices=["token", "minute", "minute5", "venue", "daily", "rate", "all"])
    ap.add_argument("--mode", default=None)
    args = ap.parse_args()
    c = KiwoomClient(args.mode)
    items = ["token", "rate", "venue", "daily", "minute", "minute5"] if args.item == "all" else [args.item]
    for it in items:
        print(f"===== {it} ({now()})", flush=True)
        {"token": m_token, "minute": m_minute, "minute5": lambda c: m_minute(c, "5"),
         "venue": m_venue, "daily": m_daily, "rate": m_rate}[it](c)


if __name__ == "__main__":
    main()
