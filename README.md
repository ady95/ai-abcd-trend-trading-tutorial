# ai-abcd-trend-trading-tutorial

위키독스 도서 **《AI로 검증하는 주도주 ABCD 눌림목 자동매매 따라하기》**의 예제코드 저장소입니다.

> 키움증권 API와 LightGBM으로 구현하는 추세 지속형 패턴 탐지·백테스트·실시간 자동매매

- 책: https://wikidocs.net/book/22000
- 저자: 이창근

## 이 저장소가 다루는 것

국내 주도주에서 **추세 지속형 ABCD 눌림목** 패턴을 실시간으로 탐지하고, 세 가지 진입 전략과 LightGBM 예측 모델의
실질적인 수익성을 거래비용 차감 후 기준으로 비교 검증한 뒤, 키움증권 API로 모의 자동매매를 구현합니다.

| 좌표 | 의미 |
|---|---|
| A | 상승 시작점(스윙 저점) |
| B | 1차 상승 고점 |
| C | A보다 높은, **확인된** 조정 저점 |
| D | 재상승 결과 — 미래에 관찰되는 값이며 진입 시 입력으로 쓰지 않음 |

하모닉 ABCD 및 D 지점 반전매매는 다루지 않습니다.

## 시작하기

```bash
git clone https://github.com/ady95/ai-abcd-trend-trading-tutorial.git
cd ai-abcd-trend-trading-tutorial
uv sync                      # Python 3.12 가상환경과 의존성 설치
cp .env.example .env         # 앱키·시크릿을 채운다 (.env는 커밋되지 않음)
uv run python scripts/check_kiwoom.py   # 토큰 발급과 현재가 조회로 연결 확인
```

## 구조

```text
src/abcd/
  broker/      키움증권 REST API 클라이언트 (시세 조회)
  collector/   과거/실시간 데이터 수집·정제
  screener/    주도주 후보 스크리닝
  pattern/     ABCD 상태 머신 및 신호 탐지
  features/    VWAP·RVOL·패턴 특성
  models/      LightGBM 학습·추론
  backtest/    이벤트 기반 백테스트
  execution/   주문·체결·포지션 관리
  risk/        손절·일 손실·비상 중지
experiments/ 장별 실측·실험 코드 (예: ch02_data_availability)
scripts/     연결 확인, 정기 작업 실행기
reports/     실측·실험 결과 요약(JSON)
data/        원천 시세 (저장소에 포함하지 않음)
```

## 환경

- Python 3.12, [uv](https://docs.astral.sh/uv/)로 의존성 관리 (`uv.lock` 고정)
- 키움증권 REST API (모의투자 키 권장)
- httpx, websockets, pandas, pyarrow, DuckDB, LightGBM, scikit-learn

API 키와 계좌정보는 `.env.example`을 `.env`로 복사해 채우세요. `.env`는 커밋되지 않습니다.

## 주의

이 저장소의 전략·임계값·수익성은 **실증 검증 전 가설**이며 투자 성과를 보장하지 않습니다.
실거래에 사용해 발생한 손실에 대해 저자는 책임지지 않습니다.

## 라이선스

MIT
