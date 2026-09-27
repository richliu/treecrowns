"""第二階段：外部圖資套疊與驗證。

1. 每個疑似光電案場加上：鄉鎮、平均標高 / 坡度（Copernicus DEM 30 m）、
   位於官方山坡地（水保法、不含六都）比例、DEM 推估山坡地（標高 ≥ 100 m 或坡度 ≥ 5%）比例、
   位於國有林事業區比例
2. 鄉鎮比對：本站偵測的新增光電面積 vs 能源署「取得施工許可之電業太陽光電案場」土地面積
3. 縣市 / 全國比對：偵測面積 vs 能源署同意備案容量、全國累計裝置容量

用法：python overlay.py
輸出：public/data/pv_sites.geojson（加欄位）、data/stats/validation.json、public/data/validation.json
"""
import glob
import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask, rasterize
from rasterio.windows import from_bounds
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, PUBLIC

EXT = DATA / "ext"
SIX = {"臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市"}
norm = lambda s: str(s).replace("台", "臺").strip()


def load_towns():
    g = gpd.read_file(DATA / "boundary" / "towns-10t.json", layer="towns").set_crs(4326, allow_override=True)
    g["county"] = g.COUNTYNAME.map(norm)
    g["town"] = g.TOWNNAME.map(norm)
    return g[["county", "town", "geometry"]]


# ---------- DEM ----------
DEM_TILES = {}
for p in glob.glob(str(EXT / "dem" / "*.tif")):
    n = Path(p).stem.split("_")
    DEM_TILES[(int(n[4][1:]), int(n[6][1:]))] = p   # Copernicus_DSM_COG_10_N23_00_E120_00_DEM


def dem_stats(geom):
    """回傳 (平均標高 m, 平均坡度 %, DEM 推估山坡地比例)。"""
    minx, miny, maxx, maxy = geom.bounds
    key = (math.floor((miny + maxy) / 2), math.floor((minx + maxx) / 2))
    p = DEM_TILES.get(key)
    if p is None:
        return None, None, None
    with rasterio.open(p) as ds:
        pad = 12 / 3600
        w = from_bounds(minx - pad, miny - pad, maxx + pad, maxy + pad, ds.transform).round_offsets().round_lengths()
        z = ds.read(1, window=w, boundless=True, fill_value=np.nan).astype(np.float32)
        tr = ds.window_transform(w)
    if z.size < 9:
        return None, None, None
    lat = (miny + maxy) / 2
    dx = abs(tr.a) * 111320 * math.cos(math.radians(lat)); dy = abs(tr.e) * 110574
    # DEM 是地表模型（含樹高、建物、面板），先以 σ = 2 像元（~60 m）平滑再算坡度，
    # 對照官方山坡地（非六都）：precision 0.21 → 0.60、recall 0.86 → 0.85
    zs = ndimage.gaussian_filter(np.nan_to_num(z, nan=0.0), 2)
    gy, gx = np.gradient(zs, dy, dx)
    slope = np.hypot(gx, gy) * 100
    inside = ~geometry_mask([geom], out_shape=z.shape, transform=tr, all_touched=True)
    if not inside.any():
        return None, None, None
    zi, si = z[inside], slope[inside]
    ok = np.isfinite(zi)
    if not ok.any():
        return None, None, None
    sl = ((zi >= 100) | (si >= 5))[ok].mean()
    return float(np.nanmean(zi)), float(np.nanmean(si)), float(sl)


def frac_in(sites_3826, layer_3826):
    """各案場落在 layer 內的面積比例。"""
    inter = gpd.overlay(sites_3826[["sid", "geometry"]], layer_3826[["geometry"]], how="intersection",
                        keep_geom_type=True)
    a = inter.assign(a=inter.area).groupby("sid")["a"].sum()
    return (a / sites_3826.set_index("sid").area).reindex(sites_3826.sid).fillna(0).clip(0, 1).values


def main():
    ts = json.loads((DATA / "stats" / "timeseries.json").read_text())
    ana = ts["analysis_years"]; base = ts["baseline"]
    towns = load_towns()

    # ---------- 1. 案場屬性 ----------
    sites = gpd.read_file(PUBLIC / "data" / "pv_sites.geojson")
    sites["sid"] = np.arange(len(sites))
    s3826 = sites.to_crs(3826)
    slope_off = gpd.read_file(EXT / "slopeland" / "slopeland115.shp").set_crs(3826, allow_override=True)
    slope_off = slope_off[slope_off.SLOPELAND.astype(str).str.contains("劃入")] if "SLOPELAND" in slope_off else slope_off
    forest = gpd.read_file(EXT / "forest" / "forest1141.shp").to_crs(3826)
    sites["slopeland_off"] = frac_in(s3826, slope_off).round(2)
    sites["nat_forest"] = frac_in(s3826, forest).round(2)
    rp = sites.set_geometry(sites.representative_point())
    j = gpd.sjoin(rp[["geometry"]], towns, how="left", predicate="within")
    sites["town"] = j["town"].groupby(level=0).first()
    sites["county"] = j["county"].groupby(level=0).first().fillna(sites.get("county"))
    sites.loc[sites.county.isin(SIX), "slopeland_off"] = np.nan    # 六都無官方圖資
    el, sl, sd = [], [], []
    for g in sites.geometry:
        a, b, c = dem_stats(g)
        el.append(a); sl.append(b); sd.append(c)
    sites["elev"] = np.round(np.array(el, dtype=float), 0)
    sites["slope"] = np.round(np.array(sl, dtype=float), 1)
    sites["slopeland_dem"] = np.round(np.array(sd, dtype=float), 2)
    sites = sites.drop(columns=["sid"])
    (PUBLIC / "data" / "pv_sites.geojson").write_text(sites.to_json(drop_id=True))
    print("sites enriched", len(sites))

    new = sites[sites.year > base].copy()
    for k in ["tree", "water", "farm", "bare"]:
        new[f"{k}_ha"] = new[f"{k}_ha"].fillna(0)
    on_slope = new.slopeland_dem >= 0.5
    in_forest = new.nat_forest >= 0.5
    site_summary = dict(
        n_sites=int(len(new)), area=round(float(new.area_ha.sum()), 1),
        by_terrain={name: {k: round(float(new.loc[m, f"{k}_ha"].sum()), 1) for k in ["tree", "water", "farm", "bare"]}
                    | {"n": int(m.sum()), "area": round(float(new.loc[m, "area_ha"].sum()), 1)}
                    for name, m in [("slopeland", on_slope), ("flat", ~on_slope), ("nat_forest", in_forest)]},
    )

    # ---------- 2. 鄉鎮比對 ----------
    plants = pd.read_csv(EXT / "pv_plants_moeaea.csv")
    plants["county"] = plants["縣市"].map(norm); plants["town"] = plants["鄉鎮區"].map(norm)
    plants["year"] = plants["申請年度"].astype(int) + 1911
    plants["land_ha"] = plants["土地面積"] / 1e4
    plants["mw"] = plants["裝置容量"] / 1e3
    pt = plants.groupby(["county", "town"]).agg(n=("mw", "size"), land_ha=("land_ha", "sum"), mw=("mw", "sum")).reset_index()

    # 偵測面積：由 pvyear / pvpred 衍生圖層逐鄉鎮累計（新增 = 完工年 > 基準年）
    towns = towns.reset_index(drop=True); towns["tid"] = np.arange(1, len(towns) + 1)
    nT = len(towns) + 1
    det = np.zeros((nT, 5))
    for f in sorted((DATA / "derived" / "pvyear").glob("*.tif")):
        with rasterio.open(f) as d:
            pvy = d.read(1); tr, crs = d.transform, d.crs
        with rasterio.open(DATA / "derived" / "pvpred" / f.name) as d:
            pred = d.read(1)
        m = pvy > 1
        if not m.any():
            continue
        tg = towns.to_crs(crs)
        tid = rasterize(zip(tg.geometry, tg.tid), out_shape=pvy.shape, transform=tr, dtype="uint16")
        det += np.bincount(tid[m].astype(np.int64) * 5 + pred[m], minlength=nT * 5).reshape(nT, 5)
    towns["det_ha"] = det[1:].sum(1) / 100
    for code, k in [(1, "tree"), (2, "water"), (3, "farm"), (4, "bare")]:
        towns[f"det_{k}"] = det[1:, code] / 100
    cmp_ = towns.drop(columns="geometry").merge(pt, on=["county", "town"], how="outer").fillna(0)
    cmp_ = cmp_[(cmp_.det_ha > 0) | (cmp_.land_ha > 0)].sort_values("land_ha", ascending=False)
    r = np.corrcoef(cmp_.land_ha, cmp_.det_ha)[0, 1] if len(cmp_) > 2 else None
    top_towns = cmp_[cmp_.land_ha >= 20]
    town_summary = dict(
        corr=round(float(r), 3) if r is not None else None,
        plants_n=int(plants.shape[0]), plants_land_ha=round(float(plants.land_ha.sum()), 1),
        plants_mw=round(float(plants.mw.sum()), 1),
        det_total=round(float(towns.det_ha.sum()), 1),
        det_in_plant_towns=round(float(cmp_.loc[cmp_.land_ha > 0, "det_ha"].sum()), 1),
        ratio_det_to_land=round(float(top_towns.det_ha.sum() / top_towns.land_ha.sum()), 3) if len(top_towns) else None,
        towns=[dict(county=r.county, town=r.town, plant_n=int(r.n), plant_land=round(r.land_ha, 1),
                    plant_mw=round(r.mw, 1), det=round(r.det_ha, 1),
                    det_tree=round(r.det_tree, 1), det_water=round(r.det_water, 1),
                    det_farm=round(r.det_farm, 1), det_bare=round(r.det_bare, 1))
               for r in cmp_.itertuples()])
    plants_by_year = plants.groupby("year").agg(n=("mw", "size"), land_ha=("land_ha", "sum"), mw=("mw", "sum")).round(1)

    # ---------- 3. 縣市 / 全國 ----------
    appr = pd.read_csv(EXT / "pv_county_approval_by_year.csv")
    appr["county"] = appr.county.map(norm)
    appr_new = appr[(appr.year > base) & (appr.year <= ana[-1])].groupby("county").kw.sum() / 1000
    county_cmp = []
    for c in ts["counties"]:
        name = norm(c["name"])
        county_cmp.append(dict(county=name, det_new=c["pv_new_total"], approved_mw=round(float(appr_new.get(name, 0)), 1),
                               ha_per_mw=round(c["pv_new_total"] / appr_new[name], 3) if appr_new.get(name, 0) > 0 else None))
    cap = pd.read_csv(EXT / "set_246.csv", encoding="utf-8-sig")
    cap = cap.set_index(cap.columns[0])[[c for c in cap.columns if "太陽光電" in c][0]]
    national = [dict(year=y, det_pv=ts["total"]["yearly"][str(y)]["pv_est"],
                     cap_mw=round(float(cap.get(y, np.nan)), 1),
                     approved_mw=round(float(appr[appr.year == y].kw.sum() / 1000), 1))
                for y in ts["years"]]

    out = dict(baseline=base, analysis_years=ana, sites=site_summary, towns=town_summary,
               plants_by_year={int(k): v for k, v in plants_by_year.to_dict("index").items()},
               counties=county_cmp, national=national)
    for p in (DATA / "stats" / "validation.json", PUBLIC / "data" / "validation.json"):
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float))
    print(json.dumps({k: out[k] for k in ["sites"]}, ensure_ascii=False)[:1500])
    print({k: v for k, v in town_summary.items() if k != "towns"})


if __name__ == "__main__":
    main()
