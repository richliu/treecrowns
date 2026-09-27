#!/bin/bash
# 分類（有合成檔的年份，平行）→ 時間序列統計 → 圖磚（平行）→ 網站
# 用法：./run_post.sh 2017 2018 ... 2025      （P=分類/圖磚並行數，預設 4）
set -e
cd "$(dirname "$0")/.."
export PYTHONWARNINGS=ignore
P=${P:-4}
for y in "$@"; do ls data/composite/$y/*.tif >/dev/null 2>&1 && echo $y; done | \
  xargs -P $P -I{} sh -c '.venv/bin/python pipeline/classify.py {} > logs/cls_{}.log 2>&1 || { echo "classify {} failed"; exit 255; }'
.venv/bin/python pipeline/timeseries.py "$@"
.venv/bin/python pipeline/sensitivity.py "$@"
.venv/bin/python pipeline/overlay.py
{ for y in "$@"; do echo "class $y"; done; for l in pvyear tree2pv treeloss pvpred; do echo "derived $l"; done; } | \
  xargs -P 3 -L 1 sh -c '.venv/bin/python pipeline/tiles.py $0 $1 > logs/tiles_$0_$1.log 2>&1 || echo "tiles $0 $1 failed"'
.venv/bin/python pipeline/build_site.py
echo "POST DONE $(date)"
