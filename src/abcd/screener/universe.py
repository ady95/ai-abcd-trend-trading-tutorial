"""대상 종목(유니버스) 구성 — KRX 일별 데이터에서 그날 매매 대상이 될 수 있는 보통주만 남긴다.

2장 실측(2026-11-04 기준)에서 확인한 제외 대상:
- 증권구분: 부동산투자회사(리츠), 사회간접자본투융자회사, 투자회사, 외국주권, 주식예탁증권(DR)
- 주식종류: 우선주(구형·신형), 종류주권
- 코스닥 소속부: SPAC, 관리종목, 투자주의환기종목, 외국기업
그날 기준일의 종목기본정보를 쓰므로 상장폐지된 종목도 그 시점에는 포함된다(생존 편향 방지).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

EXCLUDE_SECUGRP = {"부동산투자회사", "사회간접자본투융자회사", "투자회사", "외국주권", "주식예탁증권"}
EXCLUDE_SECT_KEYWORDS = ("SPAC", "관리종목", "투자주의환기", "외국기업")


def load_day(krx_dir: Path, day: str) -> pd.DataFrame:
    """그날 KOSPI+KOSDAQ 일별매매 + 종목기본정보 → 보통주 대상 종목만 (열: code, name, market, ...)."""
    rows = []
    for mkt, daily, info in (("KOSPI", "kospi_daily", "kospi_info"), ("KOSDAQ", "kosdaq_daily", "kosdaq_info")):
        d = pd.read_parquet(krx_dir / daily / f"{day}.parquet")
        i = pd.read_parquet(krx_dir / info / f"{day}.parquet")[
            ["ISU_SRT_CD", "LIST_DD", "SECUGRP_NM", "KIND_STKCERT_TP_NM", "SECT_TP_NM"]]
        i = i.rename(columns={"ISU_SRT_CD": "ISU_CD", "SECT_TP_NM": "SECT_INFO"})
        rows.append(d.merge(i, on="ISU_CD", how="left").assign(market=mkt))
    df = pd.concat(rows, ignore_index=True)
    sect = df["SECT_INFO"].fillna("") + df["SECT_TP_NM"].fillna("")
    keep = (
        (df["SECUGRP_NM"] == "주권")
        & (df["KIND_STKCERT_TP_NM"] == "보통주")
        & ~sect.str.contains("|".join(EXCLUDE_SECT_KEYWORDS))
        & (df["ACC_TRDVAL"] > 0)          # 거래정지 등으로 거래가 없던 종목 제외
    )
    out = df[keep].rename(columns={
        "ISU_CD": "code", "ISU_NM": "name", "TDD_OPNPRC": "open", "TDD_HGPRC": "high", "TDD_LWPRC": "low",
        "TDD_CLSPRC": "close", "FLUC_RT": "chg_pct", "ACC_TRDVOL": "volume", "ACC_TRDVAL": "value",
        "MKTCAP": "mktcap", "LIST_DD": "list_dd"})
    out["day"] = day
    return out[["day", "code", "name", "market", "open", "high", "low", "close", "chg_pct",
                "volume", "value", "mktcap", "list_dd"]].reset_index(drop=True)


def load_range(krx_dir: Path) -> pd.DataFrame:
    """받아 둔 모든 거래일의 대상 종목을 하나로 합친다."""
    days = sorted(p.stem for p in (krx_dir / "kospi_daily").glob("*.parquet"))
    return pd.concat([load_day(krx_dir, d) for d in days], ignore_index=True)
