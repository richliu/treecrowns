#!/bin/bash
# 逐年：合成 → 分類 → （非保留年份）刪合成檔以省空間
# 用法：./run_years.sh 2019 2020 ...     KEEP="2017 2018 2025" 為保留合成檔的年份
cd "$(dirname "$0")/.."
export PYTHONWARNINGS=ignore
KEEP=${KEEP:-"2017 2018 2019 2020 2021 2022 2023 2024 2025"}   # 合成檔已移到 NFS，全部保留
for y in "$@"; do
  echo "=== $y composite $(date)"
  P=${P:-2} pipeline/run_composites.sh $y
  echo "=== $y classify $(date)"
  .venv/bin/python pipeline/classify.py $y || exit 1
  n=$(ls data/class/$y/*.tif | wc -l)
  if [[ " $KEEP " != *" $y "* ]] && [ "$n" -ge 12 ]; then
    rm -f data/composite/$y/*.tif; echo "removed composite $y"
  fi
  df -h . | tail -1
done
echo "YEARS DONE $(date)"
