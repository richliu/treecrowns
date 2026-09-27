"""多年度逐像元時間序列分析。

以 BASELINE（2018）為統計起點；更早的年份（2017，只有 Sentinel-2A、樹冠系統性低估）只當參考，
出現在各年面積，但不參與完工年 / 前身 / 樹冠消失的判斷。

逐像元判斷，比兩兩年份相減更抗雜訊：
  - 光電完工年：第一個「該年為 PV 且下一年仍為 PV（或下一年無資料 / 已是最後一年）」的年份；
    基準年已是 PV 者視為既有
  - 前身（完工前的分析年份）依序判斷：樹冠過半 → 樹冠；水體 ≥ 1/3 → 水體（魚塭、鹽田、埤塘）；
    低植生 ≥ 裸露地 → 農地/低植生；其餘 → 裸露地/建物
  - 樹冠明確消失（年）：前一年為樹冠，該年轉為裸露地/建物/光電/水體，且下一年沒有恢復為樹冠
  - 各年各類面積：以「有效像元中的比例 × 縣市面積」估計，減少各年雲遮程度不同的影響

用法：python timeseries.py [--baseline 2018] 2017 2018 ... 2025
輸出：data/stats/timeseries.json、data/derived/<layer>/<tile>.tif、public/data/pv_sites.geojson
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize, shapes
from scipy import ndimage
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).parent))
from classify import BARE, CLASS_NAMES, LOWVEG, PV, SHADOW, TREE, WATER
from common import CLASS_DIR, DATA, PUBLIC, load_counties

NCLS = 7
DERIVED = DATA / "derived"
PV_SITE_MIN_PX = 20       # 0.2 公頃
LOSS_MIN_PX = 50          # 0.5 公頃
BASELINE = 2018

# 光電前身代碼
PRED_TREE, PRED_WATER, PRED_FARM, PRED_BARE = 1, 2, 3, 4
PRED_KEYS = {PRED_TREE: "tree", PRED_WATER: "water", PRED_FARM: "farm", PRED_BARE: "bare"}
PRED_NAMES = {"tree": "樹冠", "water": "水體（魚塭/鹽田/埤塘）", "farm": "農地/低植生", "bare": "裸露地/建物"}
PRED_COLORS = {0: (0, 0, 0, 0), PRED_TREE: (220, 0, 60, 255), PRED_WATER: (30, 144, 255, 255),
               PRED_FARM: (240, 190, 0, 255), PRED_BARE: (150, 110, 80, 255)}


def load_stack(tile, years):
    arrs = []
    for y in years:
        with rasterio.open(CLASS_DIR / str(y) / f"{tile}.tif") as ds:
            arrs.append(ds.read(1))
            prof, tr, crs = ds.profile, ds.transform, ds.crs
    return np.stack(arrs), prof, tr, crs


def analyse(C, years):
    """C: (T, H, W) uint8（只含分析年份）。回傳 first_pv_idx(-1 = 無)、pred(0..4)、loss_idx(-1 = 無)。"""
    T = len(years)
    valid = C > 0
    pv = C == PV
    tree = C == TREE
    # 光電確認：該年 PV，且下一年 PV / 無資料 / 已是最後一年
    nxt_ok = np.ones_like(pv)
    nxt_ok[:-1] = pv[1:] | ~valid[1:]
    confirmed = pv & nxt_ok
    has = confirmed.any(0)
    first = np.where(has, confirmed.argmax(0), -1).astype(np.int8)

    # 完工前（分析年份內）的前身
    idx = np.arange(T)[:, None, None]
    before = (idx < first[None]) & valid
    n_valid = before.sum(0)
    n_tree = (tree & before).sum(0)
    n_water = ((C == WATER) & before).sum(0)
    n_farm = (((C == LOWVEG) | (C == SHADOW)) & before).sum(0)
    n_bare = (((C == BARE) | (C == PV)) & before).sum(0)
    new = has & (first > 0) & (n_valid > 0)
    pred = np.zeros(C.shape[1:], np.uint8)
    pred[new & (n_bare > n_farm)] = PRED_BARE
    pred[new & (n_farm >= n_bare) & (n_farm > 0)] = PRED_FARM   # 平手算農地（整地多半是施工的一部分）
    pred[new & (n_water * 3 >= n_valid)] = PRED_WATER
    pred[new & (n_tree * 2 >= n_valid) & (n_tree >= 1)] = PRED_TREE

    # 樹冠明確消失：前一個有效年份為樹冠 → 本年為裸露/光電/水體 → 下一年（若有效）非樹冠
    cleared = np.isin(C, [BARE, PV, WATER])
    loss = np.full(C.shape[1:], -1, np.int8)
    prev_tree = np.zeros(C.shape[1:], bool)   # 最近一次有效觀測是否為樹冠
    for t in range(T):
        nxt_not_tree = ~tree[t + 1] if t + 1 < T else np.ones_like(prev_tree)
        hit = prev_tree & cleared[t] & nxt_not_tree & (loss < 0)
        loss[hit] = t
        prev_tree = np.where(valid[t], tree[t], prev_tree)
    return first, pred, loss


def vectorize_sites(first, pred, years, tr, crs, tile):
    """PV 案場多邊形：以連通區塊為單位，屬性含完工年（眾數）與各前身面積。"""
    mask = first >= 0
    lab, n = ndimage.label(mask)
    if n == 0:
        return []
    ids = np.arange(1, n + 1)
    sz = ndimage.sum(mask, lab, ids)
    big = ids[sz >= PV_SITE_MIN_PX]
    if len(big) == 0:
        return []
    lab = np.where(np.isin(lab, big), lab, 0)
    pred_px = {k: ndimage.sum(pred == code, lab, big) for code, k in PRED_KEYS.items()}
    yr_counts = np.stack([ndimage.sum(first == k, lab, big) for k in range(len(years))], 1)
    yr_mode = yr_counts.argmax(1)
    info = {}
    for j, i in enumerate(big):
        s_ = float(sz[i - 1])
        d = dict(area_ha=s_ / 100, year=int(years[yr_mode[j]]))
        for k in PRED_KEYS.values():
            d[f"{k}_ha"] = round(float(pred_px[k][j]) / 100, 2)
        d["tree_before_ha"] = d["tree_ha"]
        d["tree_frac"] = round(d["tree_ha"] * 100 / s_, 2)
        new_ha = sum(d[f"{k}_ha"] for k in PRED_KEYS.values())
        d["type"] = max(PRED_KEYS.values(), key=lambda k: d[f"{k}_ha"]) if new_ha > 0 else "existing"
        info[int(i)] = d
    feats = [dict(geometry=shape(g), tile=tile, **info[int(v)])
             for g, v in shapes(lab.astype(np.int32), mask=lab > 0, transform=tr)]
    if not feats:
        return []
    gdf = gpd.GeoDataFrame(feats, geometry="geometry", crs=crs)
    gdf["geometry"] = gdf.geometry.simplify(5)
    return gdf.to_crs(4326).to_dict("records")


def write_derived(name, arr, prof, tile, colormap=None):
    d = DERIVED / name; d.mkdir(parents=True, exist_ok=True)
    p = dict(prof, count=1, dtype="uint8", nodata=0, predictor=1)
    with rasterio.open(d / f"{tile}.tif", "w", **p) as dst:
        dst.write(arr.astype(np.uint8), 1)
        if colormap:
            dst.write_colormap(1, colormap)


def run(years, baseline=BASELINE):
    years = sorted(years)
    ana = [y for y in years if y >= baseline]          # 分析年份
    ref = [y for y in years if y < baseline]           # 參考年份（只算各年面積）
    T, A = len(years), len(ana)
    off = T - A
    counties = load_counties().reset_index(drop=True)
    counties["cid"] = np.arange(1, len(counties) + 1)
    nC = len(counties) + 1
    cls_area = np.zeros((T, nC, NCLS), np.int64)        # 各年各類像元數（0 = 無資料）
    pv_install = np.zeros((A, nC), np.int64)
    pred_install = np.zeros((A, nC, 5), np.int64)       # [年, 縣市, 前身]
    loss_year = np.zeros((A, nC), np.int64)
    sites = []

    tiles = sorted(p.stem for p in (CLASS_DIR / str(years[0])).glob("*.tif")
                   if all((CLASS_DIR / str(y) / p.name).exists() for y in years))
    for t in tiles:
        C, prof, tr, crs = load_stack(t, years)
        cg = counties.to_crs(crs)
        cid = rasterize(zip(cg.geometry, cg.cid), out_shape=C.shape[1:], transform=tr, dtype="uint8")
        core = (C > 0).any(0)   # 核心範圍內（classify 已把核心外設為 0）
        cid = np.where(core, cid, 0)
        sel = cid > 0
        for k in range(T):
            cls_area[k] += np.bincount(cid[sel].astype(np.int64) * NCLS + C[k][sel],
                                       minlength=nC * NCLS).reshape(nC, NCLS)
        first, pred, loss = analyse(C[off:], ana)
        cid64 = cid.astype(np.int64)
        for k in range(A):
            m = sel & (first == k)
            pv_install[k] += np.bincount(cid[m], minlength=nC)
            pred_install[k] += np.bincount(cid64[m] * 5 + pred[m], minlength=nC * 5).reshape(nC, 5)
            loss_year[k] += np.bincount(cid[sel & (loss == k)], minlength=nC)

        # 地圖用衍生圖層（代碼 = 分析年份索引 + 1）：光電完工年、砍樹光電、樹冠明確消失年、光電前身
        write_derived("pvyear", np.where(sel & (first >= 0), first + 1, 0), prof, t)
        write_derived("tree2pv", np.where(sel & (pred == PRED_TREE), first + 1, 0), prof, t)
        lossm = sel & (loss >= 0)
        lossm = ndimage.binary_opening(lossm, iterations=1)     # 去掉單像元雜訊
        write_derived("treeloss", np.where(lossm, loss + 1, 0), prof, t)
        write_derived("pvpred", np.where(sel, pred, 0), prof, t)
        sites += vectorize_sites(np.where(sel, first, -1), np.where(sel, pred, 0), ana, tr, crs, t)
        print(t, "ok", flush=True)

    # 縣市彙整
    ha = lambda px: round(float(px) / 100, 1)
    new_years = ana[1:]
    out = dict(years=years, analysis_years=ana, reference_years=ref, baseline=baseline,
               class_names={int(k): v for k, v in CLASS_NAMES.items()},
               pred_names=PRED_NAMES, counties=[])
    for _, r in counties.iterrows():
        c = r.cid
        area_px = cls_area[0, c].sum()
        yearly = {}
        for k, y in enumerate(years):
            v = cls_area[k, c]
            valid_px = v[1:].sum()
            frac = lambda cl: float(v[cl]) / valid_px if valid_px else 0
            yearly[y] = dict(valid_pct=round(100 * valid_px / area_px, 1) if area_px else 0,
                             tree_pct=round(100 * frac(TREE), 2),
                             tree_est=ha(frac(TREE) * area_px), tree_obs=ha(v[TREE]),
                             pv_est=ha(frac(PV) * area_px), pv_obs=ha(v[PV]),
                             bare_est=ha(frac(BARE) * area_px), water_est=ha(frac(WATER) * area_px))
        pred_by_year = {y: {PRED_KEYS[p]: ha(pred_install[k, c, p]) for p in PRED_KEYS}
                        for k, y in enumerate(ana) if k > 0}
        pred_total = {PRED_KEYS[p]: ha(pred_install[1:, c, p].sum()) for p in PRED_KEYS}
        out["counties"].append(dict(
            id=r.COUNTYID, name=r.COUNTYNAME, eng=r.COUNTYENG, area_ha=ha(area_px), yearly=yearly,
            pv_install={y: ha(pv_install[k, c]) for k, y in enumerate(ana) if k > 0},
            pred_install=pred_by_year, pred_total=pred_total,
            tree2pv_install={y: pred_by_year[y]["tree"] for y in new_years},
            tree_loss={y: ha(loss_year[k, c]) for k, y in enumerate(ana) if k > 0},
            tree2pv_total=pred_total["tree"],
            pv_new_total=ha(pv_install[1:, c].sum()),
            pv_existing_baseline=ha(pv_install[0, c]),
            tree_loss_total=ha(loss_year[1:, c].sum())))
    tot = {}
    for key in ["pv_install", "tree2pv_install", "tree_loss"]:
        tot[key] = {y: round(sum(c[key][y] for c in out["counties"]), 1) for y in new_years}
    tot["pred_install"] = {y: {k: round(sum(c["pred_install"][y][k] for c in out["counties"]), 1)
                               for k in PRED_KEYS.values()} for y in new_years}
    tot["pred_total"] = {k: round(sum(c["pred_total"][k] for c in out["counties"]), 1) for k in PRED_KEYS.values()}
    tot["yearly"] = {y: {k: round(sum(c["yearly"][y][k] for c in out["counties"]), 1)
                         for k in ["tree_est", "tree_obs", "pv_est", "pv_obs", "bare_est", "water_est"]} for y in years}
    area_all = sum(c["area_ha"] for c in out["counties"])
    for y in years:
        tot["yearly"][y]["valid_pct"] = round(sum(c["yearly"][y]["valid_pct"] * c["area_ha"] for c in out["counties"]) / area_all, 1)
    for k in ["tree2pv_total", "pv_new_total", "pv_existing_baseline", "tree_loss_total", "area_ha"]:
        tot[k] = round(sum(c[k] for c in out["counties"]), 1)
    out["total"] = tot
    sd = DATA / "stats"; sd.mkdir(exist_ok=True)
    (sd / "timeseries.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))

    # PV 案場
    gdf = gpd.GeoDataFrame(sites, geometry="geometry", crs=4326) if sites else \
        gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=4326)
    if len(gdf):
        rp = gdf.set_geometry(gdf.representative_point())
        j = gpd.sjoin(rp, counties[["COUNTYNAME", "geometry"]], how="left", predicate="within")
        gdf["county"] = j["COUNTYNAME"].groupby(level=0).first()
        gdf["lon"] = rp.geometry.x.round(5)
        gdf["lat"] = rp.geometry.y.round(5)
        gdf = gdf.drop(columns=["tile"])
    pd_ = PUBLIC / "data"; pd_.mkdir(parents=True, exist_ok=True)
    (pd_ / "pv_sites.geojson").write_text(gdf.to_json(drop_id=True))
    (pd_ / "timeseries.json").write_text(json.dumps(out, ensure_ascii=False))
    print("sites", len(gdf), "pv_new_total", tot["pv_new_total"], "pred", tot["pred_total"])


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=int, default=BASELINE)
    ap.add_argument("years", type=int, nargs="+")
    a = ap.parse_args()
    run(a.years, a.baseline)
