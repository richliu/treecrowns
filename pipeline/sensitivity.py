"""砍樹光電的定義敏感度：新增光電像元在完工前的 NDVI，依不同「樹」的定義計算面積。

讀 data/derived/pvyear（timeseries.py 產生）與各年合成檔的 NDVI 中位數 / P25。
用法：python sensitivity.py 2017 ... 2025      輸出：data/stats/sensitivity.json、public/data/sensitivity.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize

sys.path.insert(0, str(Path(__file__).parent))
from common import COMPOSITE_DIR, DATA, PUBLIC, load_counties

DEFS = [  # key, 標籤, 條件(完工前各年 NDVI 中位數的中位數 m、P25 的中位數 p)
    ("strict", "嚴格樹冠（NDVI 中位數 > 0.7 且 P25 > 0.6，本站主要定義）", lambda m, p: (m > 0.7) & (p > 0.6)),
    ("woody", "寬鬆木本（> 0.6 且 P25 > 0.5，含果園、檳榔、竹林）", lambda m, p: (m > 0.6) & (p > 0.5)),
    ("veg", "任何植被（NDVI 中位數 > 0.5，含農作物）", lambda m, p: m > 0.5),
    ("bare_water", "水體 / 裸露地（NDVI 中位數 < 0.2）", lambda m, p: m < 0.2),
]


def main(years, baseline=2018):
    years = [y for y in sorted(years) if y >= baseline]   # 與 timeseries 一致：pvyear 代碼 = 分析年份索引 + 1
    counties = load_counties().reset_index(drop=True)
    counties["cid"] = np.arange(1, len(counties) + 1)
    nC = len(counties) + 1
    acc = {k: np.zeros(nC) for k, _, _ in DEFS}
    total = np.zeros(nC)
    for f in sorted((DATA / "derived" / "pvyear").glob("*.tif")):
        with rasterio.open(f) as d:
            pvy = d.read(1); tr, crs = d.transform, d.crs
        m = pvy > 1                         # 基準年已存在者不算新增
        if not m.any():
            continue
        idx = np.nonzero(m)
        cg = counties.to_crs(crs)
        cid = rasterize(zip(cg.geometry, cg.cid), out_shape=pvy.shape, transform=tr, dtype="uint8")[idx]
        med = np.full((len(years), len(idx[0])), np.nan, np.float32); p25 = med.copy()
        for k, y in enumerate(years):
            with rasterio.open(COMPOSITE_DIR / str(y) / f.name) as d:
                a = d.read([6, 7])
            for arr, band in ((med, 0), (p25, 1)):
                v = a[band][idx]
                arr[k] = np.where(v == -32768, np.nan, v / 1e4)
        fy = pvy[idx].astype(int) - 1       # 完工年索引
        before = np.arange(len(years))[:, None] < fy[None]
        with np.errstate(all="ignore"):
            pm = np.nanmedian(np.where(before, med, np.nan), axis=0)
            pp = np.nanmedian(np.where(before, p25, np.nan), axis=0)
        ok = np.isfinite(pm)
        total += np.bincount(cid[ok], minlength=nC)
        for k, _, fn in DEFS:
            acc[k] += np.bincount(cid[ok & fn(pm, pp)], minlength=nC)
        print(f.stem, "ok", flush=True)
    out = dict(defs=[dict(key=k, label=l) for k, l, _ in DEFS],
               total=dict(pv_new=round(total.sum() / 100, 1), **{k: round(acc[k].sum() / 100, 1) for k in acc}),
               counties=[dict(name=r.COUNTYNAME, pv_new=round(total[r.cid] / 100, 1),
                              **{k: round(acc[k][r.cid] / 100, 1) for k in acc})
                         for _, r in counties.iterrows() if total[r.cid] > 0])
    for p in (DATA / "stats" / "sensitivity.json", PUBLIC / "data" / "sensitivity.json"):
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out["total"], ensure_ascii=False))


if __name__ == "__main__":
    main([int(y) for y in sys.argv[1:]])
