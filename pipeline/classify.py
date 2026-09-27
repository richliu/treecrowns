"""把年度合成影像分類成土地覆蓋類別（每個 MGRS tile 一個 UTM GeoTIFF）。

分類邏輯參考 BigGIS「Sentinel-2 影像變異分析」的決策樹 (Liu et al. 2018, 2019b)：
  Level1  NDVI > T_NDVI → 植生，否則 其它
  Level2  SI   > T_SI   → 陰影
  Level3  Gn   > T_Gn   → 低植生，否則 裸露地
並加上：
  - 樹冠：植生且全年第 25 百分位 NDVI 仍高（排除稻田等季節性作物）
  - 水體：MNDWI
  - 疑似太陽能板：NDVI 低、SWIR1 遠高於 NIR、藍光 > 紅光（見 README 校正說明）

每個 tile 只保留其 100km MGRS 核心範圍，避免相鄰 tile 重疊區重複計算。
用法：python classify.py 2017 [tiles...]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
from common import CLASS_DIR, COMPOSITE_DIR

# 類別代碼
NODATA, TREE, SHADOW, LOWVEG, BARE, WATER, PV = 0, 1, 2, 3, 4, 5, 6
CLASS_NAMES = {TREE: "樹冠", SHADOW: "陰影", LOWVEG: "低植生/農地", BARE: "裸露地/建物",
               WATER: "水體", PV: "疑似太陽能板"}

COLORMAP = {0: (0, 0, 0, 0), 1: (34, 120, 50, 255), 2: (80, 80, 80, 255),
            3: (170, 210, 110, 255), 4: (200, 180, 150, 255),
            5: (60, 120, 220, 255), 6: (230, 0, 230, 255)}

PARAMS = dict(
    T_NDVI=0.70,       # Level1 植生門檻（年中位數 NDVI）
    T_NDVI_P25=0.60,   # 樹冠：全年第 25 百分位 NDVI 仍需高於此值
    SHADOW_NIR_MAX=0.08,
    SHADOW_VIS_MAX=0.04,
    T_GN=0.0,          # 綠度指標門檻
    T_MNDWI=0.1,
    PV_NDVI_MAX=0.2,
    PV_SWIR_NIR_MIN=0.3,  # (B11-B08)/(B11+B08)
    PV_BLUE_RED_MIN=0.0,  # (B02-B04)/(B02+B04)
    PV_NIR_MAX=0.16,
    PV_SWIR_MIN=0.12,     # 排除深色水體：水的 B11 極低，比值會被雜訊放大
    PV_MIN_PIXELS=20,     # 0.2 公頃
)


def ownership_mask(ds, year, tile):
    """這個 tile 負責的像元：扣掉落在「其他已處理、同 UTM 帶 tile」100km 核心內的部分。
    （相鄰 tile 若沒處理，重疊帶仍由本 tile 負責，避免離島被漏掉）"""
    own = np.ones((ds.height, ds.width), bool)
    for p in (COMPOSITE_DIR / str(year)).glob("*.tif"):
        if p.stem == tile:
            continue
        with rasterio.open(p) as o:
            if o.crs != ds.crs:
                continue
            r0, r1, c0, c1 = core_window(o)
            # 對方核心的地圖座標 → 本 tile 的列/行
            x0 = o.transform.c + c0 * 10; y0 = o.transform.f - r0 * 10
            cc0 = int(round((x0 - ds.transform.c) / 10)); rr0 = int(round((ds.transform.f - y0) / 10))
            a0, a1 = max(0, rr0), min(ds.height, rr0 + 10000)
            b0, b1 = max(0, cc0), min(ds.width, cc0 + 10000)
            if a0 < a1 and b0 < b1:
                own[a0:a1, b0:b1] = False
    r0, r1, c0, c1 = core_window(ds)
    own[r0:r1, c0:c1] = True
    return own


def core_window(ds):
    """MGRS 100km 方格在此 tile 內的列/行範圍。"""
    ulx, uly = ds.transform.c, ds.transform.f
    x0 = np.ceil(ulx / 100000) * 100000
    y0 = np.floor(uly / 100000) * 100000
    c0 = int(round((x0 - ulx) / 10)); r0 = int(round((uly - y0) / 10))
    return r0, r0 + 10000, c0, c0 + 10000


def fit_pca(ds):
    """以縮圖取樣估計整個 tile 的 RGB 主成分（SI 需要全影像的 PC1 範圍）。"""
    small = ds.read([3, 2, 1], out_shape=(3, ds.height // 8, ds.width // 8)).astype(np.float32)
    x = small.reshape(3, -1).T
    x = x[(x > -32768).all(1)] / 10000
    mu = x.mean(0)
    w, v = np.linalg.eigh(np.cov((x - mu).T))
    pc = -v[:, -1] * np.sign(v[:, -1].sum())      # PC1 與亮度反向：越暗值越大
    pc1 = (x - mu) @ pc
    return dict(mu=mu, pc=pc, pmax=float(np.percentile(pc1, 99.9)), pmin=float(np.percentile(pc1, 0.1)))


def shadow_index(r, g, b, pca):
    """BigGIS 表 2 的 SI：RGB 主成分 PC1（正負區間分別正規化）與 HSI 的 I、S 組合。"""
    x = np.stack([r, g, b], -1)
    pc1 = (x - pca["mu"]) @ pca["pc"]
    pc1n = np.clip(np.where(pc1 > 0, pc1 / pca["pmax"], -pc1 / pca["pmin"]), -1, 1)
    s = x.sum(-1)
    inten = s / 3
    sat = 1 - 3 * x.min(-1) / np.where(s > 0, s, np.nan)
    return ((pc1n - inten) * (1 + sat) / (pc1n + inten + sat)).astype(np.float32)


def classify_array(a, pca, p=PARAMS):
    """a: (8, h, w) int16 composite。回傳 uint8 類別（尚未做太陽能板最小面積過濾）與 pv 遮罩。"""
    nod = a[5] == -32768
    f = a[:5].astype(np.float32) / 10000
    b2, b3, b4, b8, b11 = f
    ndvi = a[5] / 10000.0
    p25 = a[6] / 10000.0
    with np.errstate(divide="ignore", invalid="ignore"):
        gn = (b3 - b4) / (b3 + b4)
        mndwi = (b3 - b11) / (b3 + b11)
        swir_nir = (b11 - b8) / (b11 + b8)
        blue_red = (b2 - b4) / (b2 + b4)
        si = None  # shadow_index(b4, b3, b2, pca) 見上方說明，暫不使用

    cls = np.full(ndvi.shape, BARE, np.uint8)
    veg = ndvi > p["T_NDVI"]
    # BigGIS 的 SI 公式在 L2A 反射率上分母會跨 0、數值不穩（原文未提供尺度與門檻），
    # 改以「非植生且近紅外與可見光皆極暗」判定陰影；SI 仍計算供參考。
    shadow = (b8 < p["SHADOW_NIR_MAX"]) & ((b2 + b3 + b4) / 3 < p["SHADOW_VIS_MAX"])
    cls[~veg & ((gn > p["T_GN"]) | (ndvi > 0.3))] = LOWVEG
    cls[veg] = LOWVEG
    cls[veg & (p25 > p["T_NDVI_P25"])] = TREE
    cls[shadow & ~veg] = SHADOW
    cls[(mndwi > p["T_MNDWI"]) & (ndvi < 0.1)] = WATER
    pv = ((ndvi < p["PV_NDVI_MAX"]) & (swir_nir > p["PV_SWIR_NIR_MIN"]) &
          (blue_red > p["PV_BLUE_RED_MIN"]) & (b8 < p["PV_NIR_MAX"]) & (b11 > p["PV_SWIR_MIN"]) & ~nod)
    cls[nod] = NODATA
    return cls, pv, si


def filter_small(mask, min_px):
    lab, n = ndimage.label(mask)
    if n == 0:
        return mask
    sz = ndimage.sum(mask, lab, np.arange(1, n + 1))
    return np.isin(lab, np.nonzero(sz >= min_px)[0] + 1)


def process(year, tile, chunk=2048):
    src = COMPOSITE_DIR / str(year) / f"{tile}.tif"
    if not src.exists():
        print(f"skip {src}"); return
    out_dir = CLASS_DIR / str(year); out_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(src) as ds:
        own = ownership_mask(ds, year, tile)
        pca = fit_pca(ds)
        prof = ds.profile
        H, W = ds.height, ds.width
        cls = np.zeros((H, W), np.uint8)
        pv = np.zeros((H, W), bool)
        for r in range(0, H, chunk):
            for c in range(0, W, chunk):
                win = Window(c, r, min(chunk, W - c), min(chunk, H - r))
                a = ds.read(window=win)
                if (a[5] == -32768).all():
                    continue
                k, p, _ = classify_array(a, pca)
                cls[r:r + win.height, c:c + win.width] = k
                pv[r:r + win.height, c:c + win.width] = p
    # 閉運算補面板列間的空隙（只補被 PV 包圍的小洞，不會長出新的孤立區塊）
    pv = ndimage.binary_closing(pv, structure=np.ones((3, 3), bool)) & (cls > 0)
    cls[filter_small(pv, PARAMS["PV_MIN_PIXELS"])] = PV
    cls[~own] = NODATA
    prof.update(count=1, dtype="uint8", nodata=0, predictor=1)
    with rasterio.open(out_dir / f"{tile}.tif", "w", **prof) as dst:
        dst.write(cls, 1)
        dst.write_colormap(1, COLORMAP)
        dst.update_tags(params=json.dumps(PARAMS))
    u, c = np.unique(cls, return_counts=True)
    print(year, tile, {CLASS_NAMES.get(int(k), "nodata"): round(int(v) / 100, 1) for k, v in zip(u, c)}, "ha",
          flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int)
    ap.add_argument("tiles", nargs="*")
    a = ap.parse_args()
    tiles = a.tiles or [p.stem for p in sorted((COMPOSITE_DIR / str(a.year)).glob("*.tif"))]
    for t in tiles:
        process(a.year, t)
