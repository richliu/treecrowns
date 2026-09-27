"""把各 tile 的分類結果鑲嵌成 Web Mercator 影像並切成 XYZ PNG 圖磚，給 Leaflet 顯示。

圖層：
  class_<year>        土地覆蓋分類
  change_<y1>_<y2>    樹冠 / 太陽能板變遷
用法：python tiles.py class 2017     /    python tiles.py change 2017 2018
"""
import argparse
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject

sys.path.insert(0, str(Path(__file__).parent))
from classify import COLORMAP, LOWVEG, PV, TREE
from common import CLASS_DIR, DATA, PUBLIC

DERIVED = DATA / "derived"

ZMAX, ZMIN = 13, 7
R = 6378137.0
ORIGIN = math.pi * R
BBOX = (118.1, 21.85, 122.05, 26.4)   # 含金門、馬祖、澎湖

CHANGE_COLORS = {0: (0, 0, 0, 0), 1: (34, 120, 50, 90), 2: (255, 120, 0, 255), 3: (230, 0, 230, 255),
                 4: (120, 60, 220, 255), 5: (120, 230, 120, 255), 6: (255, 220, 120, 170)}
CHANGE_NAMES = {1: "樹冠維持", 2: "樹冠明確消失（轉為裸露地/建物）", 3: "樹冠 → 疑似太陽能板",
                4: "新增疑似太陽能板（非樹冠來源）", 5: "新增樹冠", 6: "樹冠 → 低植生（可能為季節/門檻誤差）"}


def merc(lon, lat):
    x = R * math.radians(lon)
    y = R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def change_code(c1, c2):
    out = np.zeros(c1.shape, np.uint8)
    valid = (c1 > 0) & (c2 > 0)
    out[valid & (c1 == TREE) & (c2 == TREE)] = 1
    out[valid & (c1 == TREE) & (c2 != TREE)] = 2
    out[valid & (c1 == TREE) & (c2 == LOWVEG)] = 6
    out[valid & (c1 == TREE) & (c2 == PV)] = 3
    out[valid & (c1 != TREE) & (c1 != PV) & (c2 == PV)] = 4
    out[valid & (c1 != TREE) & (c2 == TREE)] = 5
    return out


def mosaic(kind, years):
    res = 2 * ORIGIN / 256 / 2 ** ZMAX
    x0, y1 = merc(BBOX[0], BBOX[3]); x1, y0 = merc(BBOX[2], BBOX[1])
    # 對齊 ZMAX 圖磚格線
    tx0 = math.floor((x0 + ORIGIN) / (res * 256)); ty0 = math.floor((ORIGIN - y1) / (res * 256))
    tx1 = math.ceil((x1 + ORIGIN) / (res * 256)); ty1 = math.ceil((ORIGIN - y0) / (res * 256))
    W, H = (tx1 - tx0) * 256, (ty1 - ty0) * 256
    dst_tr = from_origin(-ORIGIN + tx0 * 256 * res, ORIGIN - ty0 * 256 * res, res, res)
    dst = np.zeros((H, W), np.uint8)
    base = DERIVED / years[0] if kind == "derived" else CLASS_DIR / str(years[0])
    tiles = sorted(p.stem for p in base.glob("*.tif"))
    for t in tiles:
        paths = [base / f"{t}.tif"] if kind == "derived" else [CLASS_DIR / str(y) / f"{t}.tif" for y in years]
        if not all(p.exists() for p in paths):
            continue
        arrs = []
        for p in paths:
            with rasterio.open(p) as ds:
                arrs.append(ds.read(1)); tr, crs = ds.transform, ds.crs
        src = change_code(*arrs) if kind == "change" else arrs[0]
        tmp = np.zeros_like(dst)
        reproject(src, tmp, src_transform=tr, src_crs=crs, src_nodata=0, dst_transform=dst_tr,
                  dst_crs="EPSG:3857", dst_nodata=0, resampling=Resampling.mode)
        dst = np.where(tmp > 0, tmp, dst)
        print("mosaic", t, flush=True)
    return dst, tx0, ty0


def palette(colors):
    pal = np.zeros((256, 4), np.uint8)
    for k, v in colors.items():
        pal[k] = v
    return pal


def write_level(args):
    arr, z, tx0, ty0, out, pal = args
    n = 0
    for j in range(arr.shape[0] // 256):
        for i in range(arr.shape[1] // 256):
            t = arr[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256]
            if not t.any():
                continue
            d = out / str(z) / str(tx0 + i); d.mkdir(parents=True, exist_ok=True)
            Image.fromarray(pal[t], "RGBA").save(d / f"{ty0 + j}.png", optimize=True)
            n += 1
    return z, n


# 縮小時的優先順序：稀少但重要的類別（樹冠→光電、新光電、明確消失）優先，季節雜訊（6）最低
CHANGE_RANK = np.array([0, 2, 4, 6, 5, 3, 1] + [0] * 249, np.uint8)
CHANGE_UNRANK = np.array([0, 6, 1, 5, 2, 4, 3] + [0] * 249, np.uint8)


def downsample(a):
    """變遷圖縮小一半：2x2 中取優先順序最高的代碼（讓稀少的變遷類別在小比例尺仍可見）。"""
    h, w = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
    b = CHANGE_RANK[a[:h, :w]].reshape(h // 2, 2, w // 2, 2)
    return CHANGE_UNRANK[b.max(axis=(1, 3))]


def year_ramp(stops, n=12):
    """年份代碼 1..n 的漸層色（代碼 = 年份索引 + 1）。"""
    pal = {0: (0, 0, 0, 0)}
    for k in range(1, n + 1):
        f = (k - 1) / max(1, n - 1) * (len(stops) - 1)
        i = min(int(f), len(stops) - 2); r = f - i
        pal[k] = tuple(int(stops[i][c] + (stops[i + 1][c] - stops[i][c]) * r) for c in range(3)) + (255,)
    return pal


DERIVED_COLORS = {
    "pvyear": year_ramp([(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)]),
    "tree2pv": year_ramp([(120, 0, 30), (220, 0, 60), (255, 90, 0), (255, 200, 0)]),
    "treeloss": year_ramp([(120, 50, 0), (230, 110, 0), (255, 190, 90)]),
    # 光電前身（類別）：1 樹冠 2 水體 3 農地 4 裸露地
    "pvpred": {0: (0, 0, 0, 0), 1: (220, 0, 60, 255), 2: (30, 144, 255, 255),
               3: (240, 190, 0, 255), 4: (150, 110, 80, 255)},
}
PRED_RANK = np.array([0, 4, 3, 2, 1] + [0] * 251, np.uint8)      # 縮小時優先顯示：樹冠 > 水體 > 農地 > 裸露
PRED_UNRANK = np.array([0, 4, 3, 2, 1] + [0] * 251, np.uint8)


def build(kind, years):
    import shutil
    if kind == "derived":
        name = years[0]
        pal = palette(DERIVED_COLORS[name])
    elif kind == "class":
        name = f"class_{years[0]}"; pal = palette(COLORMAP)
    else:
        name = f"change_{years[0]}_{years[1]}"; pal = palette(CHANGE_COLORS)
    arr, tx0, ty0 = mosaic(kind, years)
    out = PUBLIC / "tiles" / name
    shutil.rmtree(out, ignore_errors=True)
    jobs = []
    z = ZMAX
    while z >= ZMIN:
        jobs.append((arr, z, tx0, ty0, out, pal))
        # 下一層：先補齊成偶數起點
        if tx0 % 2:
            arr = np.pad(arr, ((0, 0), (256, 0))); tx0 -= 1
        if ty0 % 2:
            arr = np.pad(arr, ((256, 0), (0, 0))); ty0 -= 1
        if (arr.shape[1] // 256) % 2:
            arr = np.pad(arr, ((0, 0), (0, 256)))
        if (arr.shape[0] // 256) % 2:
            arr = np.pad(arr, ((0, 256), (0, 0)))
        if kind == "change":
            arr = downsample(arr)
        elif kind == "derived" and name == "pvpred":
            h, w = arr.shape
            arr = PRED_UNRANK[PRED_RANK[arr].reshape(h // 2, 2, w // 2, 2).max(axis=(1, 3))]
        elif kind == "derived":   # 保留任何有值的像元（取 2x2 最大值 = 最晚年份）
            h, w = arr.shape
            arr = arr.reshape(h // 2, 2, w // 2, 2).max(axis=(1, 3))
        else:
            arr = arr[::2, ::2]
        tx0 //= 2; ty0 //= 2; z -= 1
    with ProcessPoolExecutor(4) as ex:
        for z, n in ex.map(write_level, jobs):
            print(name, "z", z, n, "tiles", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["class", "change", "derived"])
    ap.add_argument("years", nargs="+", help="年份；derived 時為圖層名稱 pvyear / tree2pv / treeloss")
    a = ap.parse_args()
    build(a.kind, a.years if a.kind == "derived" else [int(y) for y in a.years])
