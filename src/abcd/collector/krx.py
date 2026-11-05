"""KRX 정보데이터시스템 오픈API 클라이언트 — 전 종목 일별 시세·종목 기본정보·지수.

키움 API는 종목 하나씩 조회하므로 "그날 전 종목"을 보려면 수천 번 호출해야 합니다.
KRX 오픈API는 날짜 하나로 시장 전체를 한 번에 돌려줘서, 대상 종목 구성과
일 단위 거래대금 순위에 씁니다. API마다 따로 이용 신청·승인이 필요합니다.

- 인증: 요청 헤더 AUTH_KEY (.env 의 KRX_API_KEY)
- 휴장일은 오류 없이 빈 목록이 온다 → 거래일 달력으로 쓸 수 있다
- 모든 값이 문자열이다 (2장 실측)
"""
from __future__ import annotations

import os
import time

import httpx
import pandas as pd
from dotenv import load_dotenv

BASE = "https://data-dbg.krx.co.kr/svc/apis"
ENDPOINTS = {
    "kospi_daily": "sto/stk_bydd_trd",       # 유가증권 일별매매정보
    "kosdaq_daily": "sto/ksq_bydd_trd",      # 코스닥 일별매매정보
    "kospi_info": "sto/stk_isu_base_info",   # 유가증권 종목기본정보
    "kosdaq_info": "sto/ksq_isu_base_info",  # 코스닥 종목기본정보
    "kospi_index": "idx/kospi_dd_trd",       # KOSPI 시리즈 일별시세
    "kosdaq_index": "idx/kosdaq_dd_trd",     # KOSDAQ 시리즈 일별시세
}
NUMERIC = ["TDD_CLSPRC", "CMPPREVDD_PRC", "FLUC_RT", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC",
           "ACC_TRDVOL", "ACC_TRDVAL", "MKTCAP", "LIST_SHRS",
           "CLSPRC_IDX", "CMPPREVDD_IDX", "OPNPRC_IDX", "HGPRC_IDX", "LWPRC_IDX", "PARVAL"]


class KrxClient:
    def __init__(self, min_interval: float = 0.2, timeout: float = 30):
        load_dotenv()
        key = os.getenv("KRX_API_KEY")
        if not key:
            raise RuntimeError(".env 에 KRX_API_KEY 가 없습니다")
        self.http = httpx.Client(base_url=BASE, timeout=timeout, headers={"AUTH_KEY": key})
        self.min_interval = min_interval
        self._last = 0.0
        self.calls = 0

    def get(self, name: str, bas_dd: str) -> pd.DataFrame:
        """name: ENDPOINTS 의 키, bas_dd: YYYYMMDD → DataFrame (휴장일이면 빈 DataFrame)."""
        for attempt in range(4):
            gap = time.monotonic() - self._last
            if gap < self.min_interval:
                time.sleep(self.min_interval - gap)
            self._last = time.monotonic()
            self.calls += 1
            r = self.http.get(ENDPOINTS[name], params={"basDd": bas_dd})
            if r.status_code == 401:
                raise PermissionError(f"미승인 API: {ENDPOINTS[name]}")
            if r.status_code >= 500 or r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            df = pd.DataFrame(r.json().get("OutBlock_1", []))
            for col in NUMERIC:
                if col in df:
                    df[col] = pd.to_numeric(df[col].str.replace(",", ""), errors="coerce")
            return df
        raise RuntimeError(f"{name} {bas_dd}: 재시도 실패")
