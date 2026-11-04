"""키움증권 REST API 연결 확인.

토큰 발급(au10001)과 주식기본정보 조회(ka10001) 한 번으로
.env 설정과 네트워크가 정상인지 확인합니다. 주문 API는 호출하지 않습니다.

사용:
    uv run python scripts/check_kiwoom.py            # TRADING_MODE 값(기본 paper)
    uv run python scripts/check_kiwoom.py --mode real

주의: 같은 앱키로 다른 곳에서 토큰을 새로 받으면 먼저 받은 토큰이 무효가 됩니다.
수집기가 돌고 있는 동안에는 같은 키로 이 스크립트를 실행하지 마세요.
"""
import argparse
import os
import sys

import httpx
from dotenv import load_dotenv

HOSTS = {
    "paper": "https://mockapi.kiwoom.com",
    "real": "https://api.kiwoom.com",
}


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description="키움 REST API 연결 확인")
    ap.add_argument("--mode", choices=HOSTS, default=os.getenv("TRADING_MODE", "paper"))
    ap.add_argument("--code", default="005930", help="조회할 종목코드")
    args = ap.parse_args()

    prefix = f"KIWOOM_{args.mode.upper()}_"
    appkey = os.getenv(prefix + "APP_KEY")
    secret = os.getenv(prefix + "APP_SECRET")
    if not appkey or not secret:
        print(f"[실패] .env에 {prefix}APP_KEY / {prefix}APP_SECRET 이 없습니다.")
        return 1

    host = HOSTS[args.mode]
    with httpx.Client(base_url=host, timeout=10) as client:
        r = client.post(
            "/oauth2/token",
            headers={"Content-Type": "application/json;charset=UTF-8"},
            json={"grant_type": "client_credentials", "appkey": appkey, "secretkey": secret},
        )
        body = r.json()
        token = body.get("token")
        print(f"[토큰] mode={args.mode} http={r.status_code} "
              f"return_code={body.get('return_code')} 만료={body.get('expires_dt')}")
        if not token:
            print(f"[실패] {body.get('return_msg')}")
            return 1

        r = client.post(
            "/api/dostk/stkinfo",
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {token}",
                "api-id": "ka10001",
            },
            json={"stk_cd": args.code},
        )
        info = r.json()
        print(f"[ka10001] http={r.status_code} return_code={info.get('return_code')} "
              f"종목={info.get('stk_nm')} 현재가={info.get('cur_prc')}")
        return 0 if info.get("return_code") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
