"""2장 실측 — 가격 수정 이벤트의 원인을 DART 공시 목록에서 찾기.

수정주가와 무수정 주가가 갈라지는 날짜(measure.py daily / adjcheck)가 나오면,
그 전후 공시를 조회해 권리락·액면분할·무상증자 같은 사유를 확인합니다.
.env 에 DART_API_KEY 가 필요합니다 (https://opendart.fss.or.kr 에서 발급).

사용:
    uv run python experiments/ch02_data_availability/dart_events.py 247540 20260801 20260910
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

import httpx
from dotenv import load_dotenv

API = "https://opendart.fss.or.kr/api"
# 주가 수정과 관련 있는 공시 이름에 들어가는 낱말
KEYWORDS = ("권리락", "배당락", "분할", "병합", "무상증자", "유상증자", "감자", "발행가액")


def corp_code(key: str, stock_code: str) -> str:
    """종목코드(6자리) → DART 고유번호(8자리). 전체 목록 zip을 받아 찾는다."""
    r = httpx.get(f"{API}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    root = ET.fromstring(z.read(z.namelist()[0]))
    for e in root.iter("list"):
        if e.findtext("stock_code") == stock_code:
            return e.findtext("corp_code")
    raise SystemExit(f"DART에서 종목코드 {stock_code}를 찾지 못했습니다")


def disclosures(key: str, corp: str, begin: str, end: str) -> list[dict]:
    rows, page = [], 1
    while True:
        j = httpx.get(f"{API}/list.json", params={"crtfc_key": key, "corp_code": corp, "bgn_de": begin,
                                                  "end_de": end, "page_no": page, "page_count": 100},
                      timeout=30).json()
        if j.get("status") != "000":  # 013 = 조회된 데이터 없음
            break
        rows += j["list"]
        if page >= int(j["total_page"]):
            break
        page += 1
    return sorted(rows, key=lambda r: r["rcept_dt"])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("stock_code")
    ap.add_argument("begin", help="YYYYMMDD")
    ap.add_argument("end", help="YYYYMMDD")
    ap.add_argument("--all", action="store_true", help="주가 수정과 무관한 공시도 모두 출력")
    args = ap.parse_args()
    key = os.environ["DART_API_KEY"]
    corp = corp_code(key, args.stock_code)
    rows = disclosures(key, corp, args.begin, args.end)
    print(f"{args.stock_code} (DART {corp}) {args.begin}~{args.end} 공시 {len(rows)}건")
    for r in rows:
        name = " ".join(r["report_nm"].split())
        if args.all or any(k in name for k in KEYWORDS):
            print(r["rcept_dt"], name)


if __name__ == "__main__":
    main()
