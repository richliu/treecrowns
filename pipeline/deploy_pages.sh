#!/bin/bash
# 把 public/ 發佈到 GitHub Pages（gh-pages 分支，強制覆寫；原始碼在 main 分支）
set -e
cd "$(dirname "$0")/.."
REMOTE=${REMOTE:-https://github.com/richliu/treecrowns.git}
TMP=$(mktemp -d)
rsync -a --delete public/ "$TMP/"
touch "$TMP/.nojekyll"
cd "$TMP"
git init -q -b gh-pages
git add -A
git commit -q -m "Deploy site $(date '+%Y-%m-%d %H:%M')"
git push -q -f "$REMOTE" gh-pages
cd - >/dev/null; rm -rf "$TMP"
echo "deployed -> https://richliu.github.io/treecrowns/"
