"""「樹 → 裸露地（空窗期）→ 光電」路徑分析。

對每個新增光電像元（完工年 > 基準年），看完工前的逐年類別序列，分成：
  majority     完工前多數年份是樹（= 網站目前的「砍樹光電」）
  cleared      曾經是樹（≥ 2 個分析年份，避免單年雜訊），最後一次是樹之後到完工都不是樹
               → 「先砍樹、空窗一段時間、再蓋光電」；記錄空窗年數 = 完工年 − 最後是樹的年份
  ref2017      分析年份從未是樹，但參考年 2017 是樹（基準年前就砍了）
  once         只有 1 個分析年份是樹（可能是分類雜訊）
  never        完工前從未是樹

用法：python tree_path.py 2017 2018 ... 2025   輸出：data/stats/tree_path.json、public/data/tree_path.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize

sys.path.insert(0, str(Path(__file__).parent))
from classify import BARE, LOWVEG, PV, SHADOW, TREE, WATER
from common import CLASS_DIR, DATA, PUBLIC, load_counties
from timeseries import BASELINE

CATS = ["majority", "cleared", "ref2017", "once", "never"]


def main(years, baseline=BASELINE):
    years = sorted(years)
    ana = [y for y in years if y >= baseline]
    ref = [y for y in years if y < baseline]
    A = len(ana)
    counties = load_counties().reset_index(drop=True)
    counties["cid"] = np.arange(1, len(counties) + 1)
    nC = len(counties) + 1
    cat_area = np.zeros((nC, len(CATS)))
    gap = np.zeros((nC, A))                       # cleared 的空窗年數分布
    gap_after = np.zeros((A, A))                  # [最後是樹的年份索引, 完工年索引]
    between = np.zeros(7)                         # cleared 空窗期間最常見的類別

    for f in sorted((DATA / "derived" / "pvyear").glob("*.tif")):
        with rasterio.open(f) as d:
            pvy = d.read(1); tr, crs = d.transform, d.crs
        m = pvy > 1
        if not m.any():
            continue
        idx = np.nonzero(m)
        first = pvy[idx].astype(int) - 1          # 分析年份索引
        C = np.stack([rasterio.open(CLASS_DIR / str(y) / f.name).read(1)[idx] for y in ana])   # (A, n)
        R = np.stack([rasterio.open(CLASS_DIR / str(y) / f.name).read(1)[idx] for y in ref]) if ref else None
        cg = counties.to_crs(crs)
        cid = rasterize(zip(cg.geometry, cg.cid), out_shape=pvy.shape, transform=tr, dtype="uint8")[idx]

        t = np.arange(A)[:, None]
        before = t < first[None]
        valid = (C > 0) & before
        tree = (C == TREE) & before
        n_valid, n_tree = valid.sum(0), tree.sum(0)
        last_tree = np.where(tree.any(0), A - 1 - np.argmax(tree[::-1], axis=0), -1)
        cat = np.full(len(first), 4)                                     # never
        cat[n_tree == 1] = 3                                             # once
        if R is not None:
            cat[(n_tree == 0) & (R == TREE).any(0)] = 2                  # ref2017
        cat[(n_tree >= 2)] = 1                                           # cleared（以下再覆寫 majority）
        cat[(n_tree * 2 >= n_valid) & (n_tree >= 1)] = 0                 # majority（與 timeseries 一致）
        for k in range(len(CATS)):
            cat_area[:, k] += np.bincount(cid[cat == k], minlength=nC)
        cl = cat == 1
        g = first[cl] - last_tree[cl]
        for gi in range(1, A):
            gap[:, gi] += np.bincount(cid[cl][g == gi], minlength=nC)
        np.add.at(gap_after, (last_tree[cl], first[cl]), 1)
        # 空窗期（最後是樹之後、完工之前）各類別像元年數
        mid = (t > last_tree[None]) & before & cl[None]
        between += np.bincount(C[mid], minlength=7)[:7]
        print(f.stem, "ok", flush=True)

    ha = lambda v: round(float(v) / 100, 1)
    names = {TREE: "樹冠", SHADOW: "陰影", LOWVEG: "低植生", BARE: "裸露地/建物", WATER: "水體", PV: "光電"}
    out = dict(
        baseline=baseline, analysis_years=ana, reference_years=ref,
        total={k: ha(cat_area[1:, i].sum()) for i, k in enumerate(CATS)},
        cleared_gap_years={int(gi): ha(gap[1:, gi].sum()) for gi in range(1, A) if gap[1:, gi].sum() > 0},
        cleared_by_last_tree_year={int(ana[a]): ha(gap_after[a].sum()) for a in range(A) if gap_after[a].sum() > 0},
        cleared_by_install_year={int(ana[b]): ha(gap_after[:, b].sum()) for b in range(A) if gap_after[:, b].sum() > 0},
        cleared_between_classes={names[k]: round(float(between[k]) / max(between.sum(), 1) * 100, 1) for k in names if between[k] > 0},
        counties=[dict(name=r.COUNTYNAME, **{k: ha(cat_area[r.cid, i]) for i, k in enumerate(CATS)})
                  for _, r in counties.iterrows() if cat_area[r.cid].sum() > 0],
    )
    for p in (DATA / "stats" / "tree_path.json", PUBLIC / "data" / "tree_path.json"):
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: out[k] for k in out if k != "counties"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main([int(y) for y in sys.argv[1:]])
