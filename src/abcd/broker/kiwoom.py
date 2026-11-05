"""키움증권 REST API 클라이언트 — 시세 조회 전용.

주문 API는 이 모듈에 두지 않습니다(12장 execution 모듈에서 다룸).

설계 원칙
- 토큰은 파일에 캐시해 재사용합니다. 같은 앱키로 다른 곳에서 토큰을 새로 받으면
  먼저 받은 토큰이 무효(8005)가 될 수 있으므로, 무효 응답을 받으면 한 번 다시 발급합니다.
- 호출 제한(return_code 5 / HTTP 429)은 대기 후 재시도하고, 끝내 실패하면 예외를 냅니다.
  빈 결과를 돌려주면 수집기가 "데이터 끝"으로 오인해 조용히 끊기기 때문입니다.
- 호출 수·제한 응답·지연을 CallStat에 기록해 실측 보고에 씁니다.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

HOSTS = {
    "paper": "https://mockapi.kiwoom.com",
    "real": "https://api.kiwoom.com",
}
# 호출 간 최소 간격(초). 2장 실측(2026-11-05)에서 모의 키는 초당 약 1.5~2건만 성공했고,
# 0.55초 간격 + 제한 응답 재시도가 처리량이 가장 좋았다. 실전 키 값은 미실측 가정치다.
DEFAULT_INTERVAL = {"paper": 0.55, "real": 0.15}
TOKEN_DIR = Path(os.getenv("ABCD_CACHE_DIR", Path.home() / ".cache" / "abcd"))


class KiwoomError(RuntimeError):
    """재시도 후에도 정상 응답(return_code 0)을 받지 못했다."""


@dataclass
class CallStat:
    calls: int = 0
    rate_limited: int = 0
    errors: int = 0
    token_issued: int = 0
    token_refreshed: int = 0
    latencies: list[float] = field(default_factory=list)

    def summary(self) -> dict:
        lat = sorted(self.latencies)
        med = lat[len(lat) // 2] if lat else None
        return {
            "calls": self.calls, "rate_limited": self.rate_limited, "errors": self.errors,
            "token_issued": self.token_issued, "token_refreshed": self.token_refreshed,
            "latency_median_ms": round(med * 1000) if med else None,
        }


class KiwoomClient:
    def __init__(self, mode: str | None = None, min_interval: float | None = None, timeout: float = 15):
        load_dotenv()
        self.mode = mode or os.getenv("TRADING_MODE", "paper")
        if self.mode not in HOSTS:
            raise ValueError(f"mode는 paper 또는 real: {self.mode}")
        prefix = f"KIWOOM_{self.mode.upper()}_"
        self.app_key = os.getenv(prefix + "APP_KEY")
        self.app_secret = os.getenv(prefix + "APP_SECRET")
        if not self.app_key or not self.app_secret:
            raise KiwoomError(f".env에 {prefix}APP_KEY / {prefix}APP_SECRET 이 없습니다")
        self.min_interval = DEFAULT_INTERVAL[self.mode] if min_interval is None else min_interval
        self.http = httpx.Client(base_url=HOSTS[self.mode], timeout=timeout)
        self.stat = CallStat()
        self._last_call = 0.0
        self._token_file = TOKEN_DIR / f"kiwoom_{self.mode}_token.json"

    # ---- 토큰 ----

    def _load_token(self) -> str | None:
        try:
            j = json.loads(self._token_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None
        # 만료 10분 전부터는 새로 받는다
        exp = datetime.strptime(j["expires_dt"], "%Y%m%d%H%M%S")
        if (exp - datetime.now()).total_seconds() < 600:
            return None
        return j["token"]

    def issue_token(self) -> dict:
        """토큰 발급(au10001). 캐시를 무시하고 새로 요청한다."""
        r = self.http.post(
            "/oauth2/token",
            headers={"Content-Type": "application/json;charset=UTF-8"},
            json={"grant_type": "client_credentials", "appkey": self.app_key, "secretkey": self.app_secret},
        )
        j = r.json()
        if not j.get("token"):
            raise KiwoomError(f"토큰 발급 실패: {j.get('return_code')} {j.get('return_msg')}")
        self.stat.token_issued += 1
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        self._token_file.write_text(json.dumps({"token": j["token"], "expires_dt": j["expires_dt"]}), encoding="utf-8")
        os.chmod(self._token_file, 0o600)
        return j

    def token(self) -> str:
        return self._load_token() or self.issue_token()["token"]

    # ---- 공통 호출 ----

    def _wait(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_call = time.monotonic()

    def post(self, path: str, api_id: str, body: dict, cont_yn: str = "", next_key: str = "",
             retries: int = 5) -> tuple[dict, dict]:
        """POST 호출. (응답 JSON, 소문자 응답 헤더)를 돌려준다."""
        last = ""
        refreshed = False
        for attempt in range(retries + 1):
            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {self.token()}",
                "api-id": api_id,
                "cont-yn": cont_yn,
                "next-key": next_key,
            }
            self._wait()
            self.stat.calls += 1
            t0 = time.monotonic()
            try:
                r = self.http.post(path, headers=headers, json=body)
            except httpx.HTTPError as e:
                self.stat.errors += 1
                last = f"{type(e).__name__}: {e}"
                time.sleep(2.0 * (attempt + 1))
                continue
            self.stat.latencies.append(time.monotonic() - t0)

            if r.status_code == 429:
                self.stat.rate_limited += 1
                last = "HTTP 429"
                time.sleep(1.0 * (attempt + 1))
                continue
            try:
                j = r.json()
            except ValueError:  # 본문이 비거나 JSON이 아닌 응답이 가끔 온다
                self.stat.errors += 1
                last = f"JSON 아님 (HTTP {r.status_code})"
                time.sleep(2.0 * (attempt + 1))
                continue

            rc, msg = j.get("return_code"), str(j.get("return_msg"))
            if rc in (0, None):
                return j, {k.lower(): v for k, v in r.headers.items()}
            if rc == 5 or "허용된 요청 개수" in msg:
                self.stat.rate_limited += 1
                last = msg
                time.sleep(1.0 * (attempt + 1))
                continue
            if "8005" in msg and not refreshed:
                self.stat.token_refreshed += 1
                refreshed = True
                self.issue_token()
                continue
            self.stat.errors += 1
            raise KiwoomError(f"{api_id} {body}: {rc} {msg}")
        raise KiwoomError(f"{api_id} {body}: 재시도 {retries}회 실패 ({last})")

    # ---- 시세 ----

    def stock_info(self, code: str) -> dict:
        """주식기본정보요청(ka10001)."""
        return self.post("/api/dostk/stkinfo", "ka10001", {"stk_cd": code})[0]

    def minute_chart(self, code: str, tic_scope: str = "1", adjusted: bool = True,
                     cont_yn: str = "", next_key: str = "") -> tuple[list[dict], str, str]:
        """주식분봉차트조회(ka10080) 1회 호출 → (행 목록[최신순], cont-yn, next-key).

        code: "005930"(KRX), "005930_NX"(NXT), "005930_AL"(통합)
        tic_scope: 분 단위 "1", "3", "5", "10", "15", "30", "45", "60"
        """
        body = {"stk_cd": code, "tic_scope": tic_scope, "upd_stkpc_tp": "1" if adjusted else "0"}
        j, h = self.post("/api/dostk/chart", "ka10080", body, cont_yn, next_key)
        return j.get("stk_min_pole_chart_qry") or [], h.get("cont-yn", "N"), h.get("next-key", "")

    def tick_chart(self, code: str, tic_scope: str = "1", adjusted: bool = True,
                   cont_yn: str = "", next_key: str = "") -> tuple[list[dict], str, str]:
        """주식틱차트조회(ka10079) 1회 호출 → (행 목록[최신순], cont-yn, next-key).

        tic_scope: 틱 단위 "1", "3", "5", "10", "30"
        """
        body = {"stk_cd": code, "tic_scope": tic_scope, "upd_stkpc_tp": "1" if adjusted else "0"}
        j, h = self.post("/api/dostk/chart", "ka10079", body, cont_yn, next_key)
        return j.get("stk_tic_chart_qry") or [], h.get("cont-yn", "N"), h.get("next-key", "")

    def daily_chart(self, code: str, base_dt: str, adjusted: bool = True,
                    cont_yn: str = "", next_key: str = "") -> tuple[list[dict], str, str]:
        """주식일봉차트조회(ka10081) 1회 호출 → (행 목록[최신순], cont-yn, next-key)."""
        body = {"stk_cd": code, "base_dt": base_dt, "upd_stkpc_tp": "1" if adjusted else "0"}
        j, h = self.post("/api/dostk/chart", "ka10081", body, cont_yn, next_key)
        return j.get("stk_dt_pole_chart_qry") or [], h.get("cont-yn", "N"), h.get("next-key", "")

    def iter_pages(self, fetch, *args, max_pages: int | None = None, **kwargs):
        """연속조회를 끝까지 따라가며 페이지(행 목록)를 하나씩 돌려준다."""
        cont_yn, next_key, n = "", "", 0
        while True:
            rows, cont_yn, next_key = fetch(*args, cont_yn=cont_yn, next_key=next_key, **kwargs)
            n += 1
            yield rows
            if cont_yn != "Y" or not rows or (max_pages and n >= max_pages):
                break


def to_price(value: str | None) -> int:
    """키움 시세 문자열의 등락 부호(+/-)를 떼고 정수로 바꾼다. 예: '-220500' → 220500"""
    return abs(int(value)) if value not in ("", None) else 0
