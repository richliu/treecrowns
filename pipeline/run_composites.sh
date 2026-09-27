#!/bin/bash
# 平行產製所有 tile 的年度合成：./run_composites.sh 2017 2018
cd "$(dirname "$0")/.."
TILES="51QTF 51QTG 51QUG 51RTH 51RUH 51QTE 51QUF 51QUE 51RUJ 51RTK 50QRL 50QRM 50QRK 50RRN 50RRP 50RPN 50QQM 50QQL 50QPM 50RQN 50RQP 50RQQ"
for y in "$@"; do for t in $TILES; do
  [ -f data/composite/$y/$t.tif ] && grep -q "done ->" logs/c_${y}_$t.log 2>/dev/null && continue
  [ -f data/composite/$y/$t.lock ] && continue   # 另一個佇列正在處理
  echo "$y $t"
done; done | xargs -P ${P:-3} -n 2 sh -c '.venv/bin/python pipeline/composite.py $0 $1 > logs/c_$0_$1.log 2>&1'
