#!/usr/bin/env bash
# 阶段日志就地落盘:每阶段日志写进该阶段产物目录(run 自包含可回溯)。
# 用法: e2e_stage_log.sh <run-id> <阶段...>   (阶段可为 fill/assemble/review/revise 等)
set -u
cd "$(dirname "$0")/../.."
export PYTHONIOENCODING=utf-8
BIN=.venv/Scripts/python.exe
CLI=.venv/Scripts/biaoshu
RID=${1:?用法: e2e_stage_log.sh <run-id> <阶段...>}
shift
RUN=data/runs/$RID
TSV=$RUN/timing.tsv
mkdir -p "$RUN"

stage_dir() {   # 阶段 -> 日志所在目录(与产物同目录)
  case "$1" in
    parse) echo "$RUN/01_parse";;
    template) echo "$RUN/02_template";;
    body) echo "$RUN/05_body";;
    fill) echo "$RUN/06_fill";;
    assemble) echo "$RUN/07_draft";;
    review|revise) echo "$RUN/08_review";;
    *) echo "$RUN";;                      # facts/outline 产物在 run 根
  esac
}

run_timed() {
  local stage=$1 cmd=$2
  local dir; dir=$(stage_dir "$stage"); mkdir -p "$dir"
  echo "=== [$stage] start $(date +%H:%M:%S) | log: $dir/$stage.log ==="
  local t0 t1 ms
  t0=$(date +%s%3N)
  if ! "$BIN" -u "$CLI" $cmd --run-id "$RID" > "$dir/$stage.log" 2>&1; then
    echo "!!! $stage FAILED"; tail -25 "$dir/$stage.log"; exit 1
  fi
  t1=$(date +%s%3N)
  ms=$((t1 - t0))
  [ -f "$TSV" ] || echo -e "stage\tms\tstart\tend" > "$TSV"
  echo -e "$stage\t$ms\t$t0\t$t1" >> "$TSV"
  echo "=== [$stage] done ${ms}ms ==="
}

for stage in "$@"; do
  if [ "$stage" = fill ]; then
    rm -rf "$RUN/06_fill"                      # 清空旧产物:防 harness 产出校验吃到陈旧文件
    run_timed fill "rerun fill"
  else
    run_timed "$stage" "$stage"
  fi
done

echo "=== 完成,汇总(秒) ==="
awk -F'\t' 'NR>1 {printf "%-10s %8.1fs\n", $1, $2/1000}' "$TSV"
awk -F'\t' 'NR>1 {s+=$2} END {printf "%-10s %8.1fs\n", "TOTAL", s/1000}' "$TSV"
