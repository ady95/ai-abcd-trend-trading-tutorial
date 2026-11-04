#!/usr/bin/env bash
# cron 등록용 공통 실행 래퍼
#   - 저장소 루트에서 가상환경(.venv)의 python으로 실행
#   - logs/<작업명>/YYYYMMDD.log 에 출력 저장
#   - flock으로 같은 작업의 중복 실행 방지
#
# 사용: scripts/run_job.sh <작업명> <python 스크립트> [인자...]
# 예  : scripts/run_job.sh check scripts/check_kiwoom.py
# cron: 50 8 * * 1-5 $HOME/ai-abcd-trend-trading-tutorial/scripts/run_job.sh check scripts/check_kiwoom.py
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "사용: $0 <작업명> <python 스크립트> [인자...]" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JOB="$1"; shift
LOG_DIR="$ROOT/logs/$JOB"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y%m%d).log"

cd "$ROOT"
exec 9>"$LOG_DIR/.lock"
if ! flock -n 9; then
  echo "$(date '+%F %T') [$JOB] 이미 실행 중 — 건너뜀" >> "$LOG"
  exit 0
fi

echo "$(date '+%F %T') [$JOB] 시작: $*" >> "$LOG"
set +e
"$ROOT/.venv/bin/python" -u "$@" >> "$LOG" 2>&1
rc=$?
set -e
echo "$(date '+%F %T') [$JOB] 종료 rc=$rc" >> "$LOG"
exit $rc
