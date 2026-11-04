"""2장 실측 — 키움 실시간 체결(0B)·호가잔량(0D) 웹소켓 수신 시험.

장중에 실행합니다. 원문 메시지는 data/raw/ws/<날짜>.jsonl (수신 시각 ns 포함),
요약은 reports/ch02/realtime_<날짜>.json 에 저장합니다. 주문은 하지 않습니다.

사용:
    uv run python experiments/ch02_data_availability/realtime_probe.py --minutes 30
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from abcd.broker.kiwoom import KiwoomClient  # noqa: E402

WS_URL = {
    "paper": "wss://mockapi.kiwoom.com:10000/api/dostk/websocket",
    "real": "wss://api.kiwoom.com:10000/api/dostk/websocket",
}
CODES = ["005930", "000660", "247540", "035720"]


def kst_delay_ms(hhmmss: str, recv: datetime) -> float | None:
    """체결시간(필드 20, HHMMSS)과 수신 시각의 차이(ms). 초 단위 필드라 ±1초 오차가 있다."""
    try:
        t = recv.replace(hour=int(hhmmss[:2]), minute=int(hhmmss[2:4]), second=int(hhmmss[4:6]), microsecond=0)
    except (ValueError, TypeError):
        return None
    return (recv - t).total_seconds() * 1000


async def run(mode: str, minutes: float) -> dict:
    client = KiwoomClient(mode)
    token = client.token()
    day = datetime.now().strftime("%Y%m%d")
    raw_path = ROOT / "data" / "raw" / "ws" / f"{day}.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    counts: Counter = Counter()
    per_item: dict = defaultdict(Counter)
    first_values: dict = {}
    delays: list[float] = []
    events: list[dict] = []
    reconnects = pings = 0
    deadline = time.monotonic() + minutes * 60

    with raw_path.open("a", encoding="utf-8") as fp:
        while time.monotonic() < deadline:
            try:
                async with websockets.connect(WS_URL[mode], ping_interval=None, max_size=None) as ws:
                    await ws.send(json.dumps({"trnm": "LOGIN", "token": token}))
                    login = json.loads(await ws.recv())
                    events.append({"t": datetime.now().isoformat(), "event": "LOGIN",
                                   "return_code": login.get("return_code"), "return_msg": login.get("return_msg")})
                    print("LOGIN", login.get("return_code"), login.get("return_msg"), flush=True)
                    if login.get("return_code") != 0:
                        break
                    await ws.send(json.dumps({"trnm": "REG", "grp_no": "1", "refresh": "1",
                                              "data": [{"item": CODES, "type": ["0B", "0D"]}]}))
                    while time.monotonic() < deadline:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            events.append({"t": datetime.now().isoformat(), "event": "30초 무수신"})
                            continue
                        recv = datetime.now()
                        fp.write(f"{time.time_ns()}\t{raw}\n")
                        msg = json.loads(raw)
                        trnm = msg.get("trnm")
                        counts[trnm] += 1
                        if trnm == "PING":
                            pings += 1
                            await ws.send(raw)  # 서버 PING은 그대로 돌려보내야 연결이 유지된다
                        elif trnm == "REAL":
                            for d in msg.get("data", []):
                                typ, item = d.get("type"), d.get("item")
                                per_item[typ][item] += 1
                                first_values.setdefault(typ, d.get("values"))
                                if typ == "0B":
                                    ms = kst_delay_ms(d.get("values", {}).get("20", ""), recv)
                                    if ms is not None:
                                        delays.append(ms)
                        elif trnm == "REG":
                            events.append({"t": recv.isoformat(), "event": "REG",
                                           "return_code": msg.get("return_code"), "return_msg": msg.get("return_msg")})
                            print("REG", msg.get("return_code"), msg.get("return_msg"), flush=True)
                        else:
                            events.append({"t": recv.isoformat(), "event": trnm, "raw": raw[:300]})
            except (websockets.ConnectionClosed, OSError) as e:
                reconnects += 1
                events.append({"t": datetime.now().isoformat(), "event": "연결 끊김", "detail": repr(e)[:200]})
                print("연결 끊김 → 재접속", repr(e)[:120], flush=True)
                await asyncio.sleep(3)

    delays.sort()
    pct = (lambda p: round(delays[int(len(delays) * p)]) if delays else None)
    return {
        "mode": mode, "day": day, "minutes": minutes, "codes": CODES,
        "messages": dict(counts), "pings": pings, "reconnects": reconnects,
        "real_by_type_item": {k: dict(v) for k, v in per_item.items()},
        "first_values": first_values,
        "trade_delay_ms_p50_p90_p99": [pct(0.5), pct(0.9), pct(0.99)],
        "events": events[:50],
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=None)
    ap.add_argument("--minutes", type=float, default=30)
    args = ap.parse_args()
    mode = args.mode or KiwoomClient().mode
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    res = asyncio.run(run(mode, args.minutes))
    res["started_at"] = started
    out = ROOT / "reports" / "ch02" / f"realtime_{res['day']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("messages", "pings", "reconnects", "trade_delay_ms_p50_p90_p99")},
                     ensure_ascii=False))
    print(f"[저장] {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
