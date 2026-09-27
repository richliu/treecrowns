"""以 Jinja2 模板產生靜態網站到 public/（多年度 + 第二階段驗證）。

資料來源：data/stats/timeseries.json、sensitivity.json、validation.json、public/data/pv_sites.geojson
用法：python build_site.py
"""
import csv
import datetime
import json
import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).parent))
from classify import PARAMS
from common import DATA, PUBLIC, ROOT, load_counties
from tiles import DERIVED_COLORS

SITE = ROOT / "site"
TREE_FRAC_SITE = 0.3   # 案場有 ≥30% 面積原為樹冠 → 列為「砍樹光電」
PRED = [("water", "水體（魚塭/鹽田/埤塘）", "#1e90ff"), ("farm", "農地/低植生", "#f0be00"),
        ("bare", "裸露地/建物", "#966e50"), ("tree", "樹冠（砍樹光電）", "#dc003c")]


DAAN_PARK_HA = 25.89      # 大安森林公園
FIELD_HA = 0.714          # 標準足球場 105 × 68 m
UNIT_NOTE = "1 公頃 = 10,000 平方公尺（100 m × 100 m）≈ 3,025 坪 ≈ 1.03 甲 ≈ 1.4 個標準足球場；大安森林公園約 26 公頃"


def eq(ha):
    """把公頃換成一般人有感的比較。"""
    if ha is None:
        return ""
    if ha >= DAAN_PARK_HA * 10:
        return f"≈ {ha / DAAN_PARK_HA:,.0f} 座大安森林公園"
    if ha >= DAAN_PARK_HA * 0.9:
        return f"≈ {ha / DAAN_PARK_HA:.1f} 座大安森林公園"
    return f"≈ {ha / FIELD_HA:,.0f} 個足球場"


def human(n):
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def rgb(c):
    return "#%02x%02x%02x" % c[:3]


def load_json(p):
    return json.loads(p.read_text()) if p.exists() else None


def main():
    S = json.loads((DATA / "stats" / "timeseries.json").read_text())
    V = load_json(DATA / "stats" / "validation.json")
    sens = load_json(DATA / "stats" / "sensitivity.json")
    TP = load_json(DATA / "stats" / "tree_path.json")
    tiers = None
    if TP:
        tt, cum = TP["total"], 0
        tiers = []
        for k, label, note in [
                ("majority", "完工前多數年份是樹", "本站主要數字；含砍樹後空窗 1–2 年"),
                ("cleared", "先砍樹、空窗多年再蓋", "≥ 2 年是樹，之後到完工都不是樹；空窗多為 3–6 年；混有「為了蓋工廠而砍、屋頂才裝光電」的案例"),
                ("ref2017", f"{S['baseline']} 年以前就已砍除", "分析年份從未是樹，只有參考年 2017 是樹"),
                ("once", "只有 1 年被判為樹", "證據弱，可能是果園 / 作物被誤判的雜訊")]:
            cum += tt[k]
            tiers.append(dict(key=k, label=label, note=note, ha=tt[k], cum=round(cum, 1)))
        gaps = TP["cleared_gap_years"]
        top3 = [int(g) for g, v in sorted(gaps.items(), key=lambda kv: -kv[1])[:3]]
        TP["gap_main"] = f"{min(top3)}–{max(top3)} 年"
    years = S["years"]; ana = S["analysis_years"]; ref = S["reference_years"]; base = S["baseline"]
    ys = [str(y) for y in years]; b, yN = str(base), ys[-1]
    T = S["total"]; P = T["pred_total"]; newtot = T["pv_new_total"] or 1
    for c in S["counties"]:
        c["tree_pct0"] = c["yearly"][b]["tree_pct"]
        c["tree_pctN"] = c["yearly"][yN]["tree_pct"]
        c["valid_min"] = min(c["yearly"][str(y)]["valid_pct"] for y in ana)
        c["t2pv_share"] = round(100 * c["tree2pv_total"] / c["pv_new_total"], 1) if c["pv_new_total"] else 0
    S["counties"].sort(key=lambda c: -c["pv_new_total"])

    pub_data = PUBLIC / "data"; pub_data.mkdir(parents=True, exist_ok=True)
    g = load_counties()
    by_id = {c["id"]: c for c in S["counties"]}
    for k in ["tree2pv_total", "pv_new_total", "tree_loss_total", "tree_pct0", "tree_pctN"]:
        g[k] = [by_id[i][k] if i in by_id else None for i in g.COUNTYID]
    for k, _, _ in PRED:
        g[f"pv_{k}"] = [by_id[i]["pred_total"][k] if i in by_id else None for i in g.COUNTYID]
    g = g.rename(columns={"COUNTYNAME": "name"})
    g["geometry"] = g.geometry.simplify(0.0005)
    (pub_data / "counties.geojson").write_text(g.drop(columns=["COUNTYENG"]).to_json(drop_id=True))

    new_years = [str(y) for y in ana[1:]]
    with open(pub_data / f"counties_{base}_{yN}.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["縣市", "縣市面積(公頃)"] + [f"樹冠比例{y}%" for y in ys] + [f"疑似光電{y}(公頃)" for y in ys]
                   + [f"新增光電{y}(公頃)" for y in new_years]
                   + [f"新增光電_前身{n}(公頃)" for _, n, _ in PRED]
                   + [f"樹冠明確消失{y}(公頃)" for y in new_years] + ["最低有效涵蓋率%（分析年份）"])
        for c in S["counties"]:
            w.writerow([c["name"], c["area_ha"]] + [c["yearly"][y]["tree_pct"] for y in ys]
                       + [c["yearly"][y]["pv_est"] for y in ys] + [c["pv_install"][y] for y in new_years]
                       + [c["pred_total"][k] for k, _, _ in PRED]
                       + [c["tree_loss"][y] for y in new_years] + [c["valid_min"]])

    sites = json.loads((pub_data / "pv_sites.geojson").read_text())["features"]
    newsites = [f["properties"] for f in sites if f["properties"]["year"] > base]
    top = sorted((p for p in newsites if p["tree_frac"] >= TREE_FRAC_SITE),
                 key=lambda p: -p["tree_ha"])[:20]
    n_sites_tree = sum(1 for p in newsites if p["tree_frac"] >= TREE_FRAC_SITE)

    fmt = lambda v: f"{v:,.0f}"
    pct = lambda v: f"{100 * v / newtot:.1f}%"
    pvb, pvN = T["yearly"][b]["pv_est"], T["yearly"][yN]["pv_est"]
    cards = [
        (f"新增疑似光電 {base + 1}–{yN}", fmt(T["pv_new_total"]), "公頃", "text-primary",
         f"{base} 已存在 {fmt(T['pv_existing_baseline'])} 公頃；{b} → {yN}：{fmt(pvb)} → {fmt(pvN)}"),
        ("原為水體（漁電 / 鹽田 / 埤塘）", fmt(P["water"]), "公頃", "text-info", f"佔新增 {pct(P['water'])}"),
        ("原為農地 / 低植生", fmt(P["farm"]), "公頃", "text-warning-emphasis", f"佔新增 {pct(P['farm'])}"),
        ("原為樹冠（砍樹光電）", fmt(P["tree"]), "公頃", "text-danger",
         f"佔新增 {pct(P['tree'])}" + (f"；含砍樹後空窗多年再蓋約 {fmt(tiers[1]['cum'])} 公頃，最寬 {fmt(tiers[-1]['cum'])} 公頃" if tiers else "")),
        ("原為裸露地 / 建物", fmt(P["bare"]), "公頃", "", f"佔新增 {pct(P['bare'])}（含整地、鹽田）"),
        (f"樹冠明確消失 {base + 1}–{yN}", fmt(T["tree_loss_total"]), "公頃", "",
         "轉為裸露地/建物/光電/水體且隔年未恢復（含崩塌）"),
        ("疑似砍樹光電案場", f"{n_sites_tree:,}", "處", "", f"≥ 0.2 公頃、原樹冠 ≥ {int(TREE_FRAC_SITE*100)}%"),
        ("分析年份", f"{base}–{yN}", "", "", f"{', '.join(map(str, ref))} 為參考年（只有 S2A，樹冠低估）" if ref else ""),
    ]
    area_vals = {0: T["pv_new_total"], 1: P["water"], 2: P["farm"], 3: P["tree"], 4: P["bare"], 5: T["tree_loss_total"]}
    cards = [c + (eq(area_vals[i]) if i in area_vals else "",) for i, c in enumerate(cards)]
    files = [(f"data/counties_{base}_{yN}.csv", "縣市逐年統計表（Excel 可直接開啟），含新增光電前身"),
             ("data/timeseries.json", "完整逐年統計（縣市 × 年份 × 前身）"),
             ("data/pv_sites.geojson", "疑似光電案場：完工年、面積、各前身面積、鄉鎮、標高、坡度、山坡地 / 國有林比例"),
             ("data/validation.json", "第二階段驗證：鄉鎮比對、縣市容量比對、地形 / 國有林統計"),
             ("data/sensitivity.json", "砍樹光電定義敏感度（嚴格 / 寬鬆 / 任何植被）"),
             ("data/tree_path.json", "「先砍樹、空窗、再蓋光電」路徑分析：各層級面積、空窗年數、空窗期類別、縣市"),
             ("data/counties.geojson", "縣市界與統計屬性"),
             ("slides/treecrowns.pptx", "成果簡報（PowerPoint）")]
    sizes = {f: human((PUBLIC / f).stat().st_size) for f, _ in files if (PUBLIC / f).exists()}
    ramp = {k: [rgb(DERIVED_COLORS[k][i + 1]) for i in range(len(ana))] for k in DERIVED_COLORS if k != "pvpred"}

    env = Environment(loader=FileSystemLoader(SITE / "templates"), autoescape=True)
    env.filters["eq"] = eq
    common = dict(root="", y1=b, y2=yN, years=years, ana=ana, ref=ref, base=base, pred=PRED,
                  has_validation=V is not None, unit_note=UNIT_NOTE,
                  generated=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    class_years = [y for y in years if (PUBLIC / "tiles" / f"class_{y}").exists()]
    sj = json.dumps(S, ensure_ascii=False)
    pages = {
        "index.html": dict(cards=cards, top_sites=top, sens=sens, tiers=tiers, TP=TP, T_new=T["pv_new_total"], summary_json=sj),
        "map.html": dict(ramp_json=json.dumps(ramp), class_years=class_years, tree_frac=TREE_FRAC_SITE),
        "counties.html": dict(counties=S["counties"], summary_json=sj),
        "method.html": dict(params=dict(PARAMS, max_scenes=15),
                            params_json=json.dumps(PARAMS, indent=2, ensure_ascii=False),
                            tree_frac=TREE_FRAC_SITE, tiers=tiers, TP=TP),
        "data.html": dict(files=files, sizes=sizes),
    }
    pages["about.html"] = dict(T=T, P=P, V=V, sens=sens, tiers=tiers, TP=TP)
    if V:
        pages["validation.html"] = dict(V=V, v_json=json.dumps(V, ensure_ascii=False), summary_json=sj)
    for name, ctx in pages.items():
        (PUBLIC / name).write_text(env.get_template(name).render(page=name, **common, **ctx), encoding="utf-8")
    shutil.copytree(SITE / "static", PUBLIC / "static", dirs_exist_ok=True)
    print("site built ->", PUBLIC)


if __name__ == "__main__":
    main()
