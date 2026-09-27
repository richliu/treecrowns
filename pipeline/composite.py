"""產生單一 MGRS tile、單一年度的 Sentinel-2 L2A 年度去雲中位數合成影像。

作法（對應 BigGIS「Sentinel-2 影像變異分析」第 1 步：先排除雲與陰影）：
  1. STAC 搜尋該 tile 該年所有 L2A 影像，依雲量挑 N 張
  2. 以 SCL 場景分類遮掉雲 / 雲影 / 卷雲 / 飽和 / 無資料，另外以藍光反射率 > 0.15 排除殘雲薄霧
  3. 逐條帶 (strip) 讀取 COG 視窗，只處理與陸地相交的條帶
  4. 每個像元取各 band 中位數，另計 NDVI 中位數與第 25 百分位 (判斷「全年持續有植被」)

用法：python composite.py 2017 51QTF [--max-scenes 15]
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.windows import Window
from shapely.geometry import box, mapping
from shapely.ops import unary_union

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from common import (BANDS_OUT, COLLECTION, COMPOSITE_DIR, SCL_VALID, STAC_ASSET,
                    STAC_URL, TILES_PRIMARY, load_counties, set_gdal_env)

CHUNK = 2048   # 對齊 COG 1024 block（20m band 為 2048 個 10m 像元）
TILE_PX = 10980


def search_scenes(tile, year, max_scenes, max_cloud=70):
    from pystac_client import Client
    c = Client.open(STAC_URL)
    items = list(c.search(collections=[COLLECTION],
                          query={"grid:code": {"eq": f"MGRS-{tile}"},
                                 "eo:cloud_cover": {"lt": max_cloud}},
                          datetime=f"{year}-01-01/{year}-12-31",
                          max_items=500).items())
    # 同一天可能有多個處理版本，只留最新
    by_date = {}
    for it in items:
        d = it.id.split("_")[2]
        if d not in by_date or it.id > by_date[d].id:
            by_date[d] = it
    items = list(by_date.values())

    def score(it):
        p = it.properties
        return p.get("eo:cloud_cover", 100) + 0.5 * p.get("s2:nodata_pixel_percentage", 0)

    items.sort(key=score)
    return items[:max_scenes]


def boa_offset(item):
    p = item.properties
    if p.get("earthsearch:boa_offset_applied"):
        return 0
    try:
        return 1000 if float(p.get("s2:processing_baseline", "0")) >= 4.0 else 0
    except ValueError:
        return 0


def land_mask(tile, crs, transform, primary_footprints):
    """陸地遮罩；次要 tile 只保留主要 tile 蓋不到的陸地。"""
    g = load_counties()
    land = unary_union(list(g.geometry.buffer(0.0005)))
    if tile not in TILES_PRIMARY and primary_footprints:
        land = land.difference(unary_union(primary_footprints).buffer(-0.0003))
    import geopandas as gpd
    land_utm = gpd.GeoSeries([land], crs=4326).to_crs(crs).iloc[0]
    if land_utm.is_empty:
        return np.zeros((TILE_PX, TILE_PX), bool)
    return rasterize([(mapping(land_utm), 1)], out_shape=(TILE_PX, TILE_PX),
                     transform=transform, dtype="uint8", all_touched=True).astype(bool)


def primary_tile_footprints(year):
    """主要 tile 的 4326 外框（以任一景的 proj 資訊取得）。"""
    from pystac_client import Client
    import geopandas as gpd
    c = Client.open(STAC_URL)
    fps = []
    for t in TILES_PRIMARY:
        it = next(c.search(collections=[COLLECTION],
                           query={"grid:code": {"eq": f"MGRS-{t}"}},
                           datetime=f"{year}-01-01/{year}-12-31", max_items=1).items(), None)
        if it is None:
            continue
        with rasterio.open(it.assets["scl"].href) as ds:
            b = box(*ds.bounds)
            fps.append(gpd.GeoSeries([b], crs=ds.crs).to_crs(4326).iloc[0])
    return fps


def read_window(href, row0, col0, nrows, ncols, scale):
    """讀取 10m 格網上的區塊；20m band 讀完再放大成 10m。"""
    with rasterio.open(href) as ds:
        if scale == 1:
            return ds.read(1, window=Window(col0, row0, ncols, nrows))
        a = ds.read(1, window=Window(col0 // 2, row0 // 2, (ncols + 1) // 2, (nrows + 1) // 2))
        return np.repeat(np.repeat(a, 2, axis=0), 2, axis=1)[:nrows, :ncols]


def nan_percentile_sorted(stack, count, q):
    """stack 已沿 axis0 排序（NaN 在後）；依有效數 count 取第 q 百分位（線性內插）。"""
    pos = (count - 1).clip(min=0) * q
    lo = np.floor(pos).astype(np.int64)
    hi = np.minimum(lo + 1, (count - 1).clip(min=0))
    frac = (pos - lo).astype(np.float32)
    vlo = np.take_along_axis(stack, lo[None], 0)[0]
    vhi = np.take_along_axis(stack, hi[None], 0)[0]
    out = vlo + (vhi - vlo) * frac
    out[count == 0] = np.nan
    return out


def composite_chunk(items, offsets, pool, row0, col0, nrows, ncols, m):
    n = len(items)
    jobs = {}
    for k, it in enumerate(items):
        for b in ["SCL", "B02", "B03", "B04", "B08", "B11"]:
            scale = 2 if b in ("SCL", "B11") else 1
            jobs[(k, b)] = pool.submit(read_window, it.assets[STAC_ASSET[b]].href,
                                       row0, col0, nrows, ncols, scale)
    data = {}
    for key, f in jobs.items():
        try:
            data[key] = f.result()
        except Exception as e:  # 單一檔讀取失敗就把該景視為無效
            print(f"  read fail {items[key[0]].id} {key[1]}: {e}", flush=True)
            data[key] = None

    valid = np.zeros((n, nrows, ncols), bool)
    haze = np.zeros((n, nrows, ncols), bool)
    for k in range(n):
        if any(data[(k, b)] is None for b in ["SCL", "B02", "B03", "B04", "B08", "B11"]):
            continue
        valid[k] = np.isin(data[(k, "SCL")], SCL_VALID) & m & (data[(k, "B08")] > 0)
        haze[k] = (data[(k, "B02")].astype(np.int32) - offsets[k]) >= 1500   # 殘雲/霧：藍光反射率 > 0.15
    # 藍光規則只在還有其他乾淨觀測時才套用；整年都很亮的像元（白色屋頂、鹽田）保留 SCL 結果
    strict = valid & ~haze
    has_strict = strict.any(0)
    valid = np.where(has_strict[None], strict, valid)
    del haze, strict
    count = valid.sum(0)

    def stack(b):
        s = np.full((n, nrows, ncols), np.nan, np.float32)
        for k in range(n):
            if data[(k, b)] is not None:
                s[k] = np.where(valid[k], (data[(k, b)].astype(np.float32) - offsets[k]) / 10000.0, np.nan)
        return s

    out = np.full((len(BANDS_OUT), nrows, ncols), -32768, np.int16)
    red, nir = stack("B04"), stack("B08")
    ndvi = (nir - red) / (nir + red + 1e-6)
    for j, b in enumerate(["B02", "B03", "B04", "B08", "B11"]):
        s = red if b == "B04" else nir if b == "B08" else stack(b)
        s.sort(axis=0)
        med = nan_percentile_sorted(s, count, 0.5)
        out[j] = np.where(np.isnan(med), -32768, np.round(med * 10000)).astype(np.int16)
    ndvi.sort(axis=0)
    for j, q in [(5, 0.5), (6, 0.25)]:
        v = nan_percentile_sorted(ndvi, count, q)
        out[j] = np.where(np.isnan(v), -32768, np.round(np.clip(v, -1, 1) * 10000)).astype(np.int16)
    # 反射率 / NDVI 量化到 0.001（遠小於 Sentinel-2 輻射精度），檔案約小 30%
    q = out[:7] != -32768
    out[:7] = np.where(q, (out[:7].astype(np.int32) + 5) // 10 * 10, -32768).astype(np.int16)
    out[:, count == 0] = -32768
    out[7] = np.where(m, count, -32768)
    return out, float(count[m].mean())


def process(tile, year, max_scenes, workers=None):
    """外層加鎖，避免兩個佇列同時處理同一個 tile。"""
    import os
    workers = workers or int(os.environ.get("COMPOSITE_THREADS", "32"))
    lock = COMPOSITE_DIR / str(year) / f"{tile}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(f"[{tile} {year}] locked by another run, skip"); return
    try:
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        _process(tile, year, max_scenes, workers)
    finally:
        lock.unlink(missing_ok=True)


def _process(tile, year, max_scenes, workers):
    set_gdal_env()
    t0 = time.time()
    items = search_scenes(tile, year, max_scenes)
    if not items:
        print(f"[{tile} {year}] no scenes"); return
    print(f"[{tile} {year}] {len(items)} scenes: " +
          ", ".join(f"{i.id.split('_')[2]}({i.properties['eo:cloud_cover']:.0f}%)" for i in items))

    with rasterio.open(items[0].assets["red"].href) as ds:
        crs, transform = ds.crs, ds.transform
    fps = [] if tile in TILES_PRIMARY else primary_tile_footprints(year)
    mask = land_mask(tile, crs, transform, fps)
    if not mask.any():
        print(f"[{tile} {year}] no land to process"); return

    out_dir = COMPOSITE_DIR / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tile}.tif"
    profile = dict(driver="GTiff", width=TILE_PX, height=TILE_PX, count=len(BANDS_OUT),
                   dtype="int16", crs=crs, transform=transform, nodata=-32768,
                   tiled=True, blockxsize=512, blockysize=512, compress="zstd",
                   predictor=2, BIGTIFF="IF_SAFER")
    offsets = [boa_offset(it) for it in items]
    pool = ThreadPoolExecutor(workers)

    with rasterio.open(out_path, "w", **profile) as dst:
        for i, name in enumerate(BANDS_OUT, 1):
            dst.set_band_description(i, name)
        dst.update_tags(scenes=",".join(it.id for it in items), year=str(year), tile=tile)
        chunks = [(r, c) for r in range(0, TILE_PX, CHUNK) for c in range(0, TILE_PX, CHUNK)
                  if mask[r:r + CHUNK, c:c + CHUNK].any()]
        print(f"[{tile} {year}] {len(chunks)} land chunks", flush=True)
        for n, (row0, col0) in enumerate(chunks, 1):
            nrows, ncols = min(CHUNK, TILE_PX - row0), min(CHUNK, TILE_PX - col0)
            m = mask[row0:row0 + nrows, col0:col0 + ncols]
            out, mc = composite_chunk(items, offsets, pool, row0, col0, nrows, ncols, m)
            dst.write(out, window=Window(col0, row0, ncols, nrows))
            print(f"[{tile} {year}] chunk {n}/{len(chunks)} land={m.mean():.2f} "
                  f"meancount={mc:.1f} t={time.time()-t0:.0f}s", flush=True)
    pool.shutdown()
    print(f"[{tile} {year}] done -> {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int)
    ap.add_argument("tiles", nargs="+")
    ap.add_argument("--max-scenes", type=int, default=15)
    a = ap.parse_args()
    for t in a.tiles:
        process(t, a.year, a.max_scenes)
