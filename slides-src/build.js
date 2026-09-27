// 成果簡報：node build.js → ../public/slides/treecrowns.pptx
// 數字全部讀自 data/stats/*.json 與 public/data/pv_sites.geojson，重跑分析後重建即可更新。
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const ROOT = path.resolve(__dirname, "..");
const J = p => JSON.parse(fs.readFileSync(path.join(ROOT, p), "utf8"));
const S = J("data/stats/timeseries.json");
const V = J("data/stats/validation.json");
const SENS = J("data/stats/sensitivity.json");
const TP = J("data/stats/tree_path.json");
const TIERS = (() => { let c = 0; return [["majority", "多數年份是樹"], ["cleared", "＋ 先砍樹、空窗多年再蓋"],
  ["ref2017", "＋ 2018 前已砍"], ["once", "＋ 只有 1 年是樹"]].map(([k, l]) => { c += TP.total[k]; return { k, l, ha: TP.total[k], cum: c }; }); })();
const TMAX = TIERS[TIERS.length - 1].cum;
const SITES = J("public/data/pv_sites.geojson").features.map(f => f.properties);
const T = S.total, P = T.pred_total, BASE = S.baseline;
const YN = S.analysis_years[S.analysis_years.length - 1];
const NEWY = S.analysis_years.slice(1).map(String);

// ---------- 樣式 ----------
const FONT = "Microsoft JhengHei";
const C = {
  forest: "1F4D2B", forest2: "2E6B3E", leaf: "CFE3C7", sun: "F0BE00", ink: "1D2A22", muted: "5F6B63",
  white: "FFFFFF", paper: "F4F8F2",
  water: "1E90FF", farm: "E0A800", bare: "966E50", tree: "DC003C",
};
const PRED = [["water", "水體（魚塭 / 鹽田）", C.water], ["farm", "農地 / 低植生", C.farm],
              ["bare", "裸露地 / 建物", C.bare], ["tree", "樹林（砍樹光電）", C.tree]];
const DAAN = 25.89, FIELD = 0.714;
const fmt = (v, d = 0) => v.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const eq = ha => ha >= DAAN * 10 ? `≈ ${fmt(ha / DAAN)} 座大安森林公園`
  : ha >= DAAN * 0.9 ? `≈ ${fmt(ha / DAAN, 1)} 座大安森林公園` : `≈ ${fmt(ha / FIELD)} 個足球場`;
const pct = v => `${fmt(100 * v / T.pv_new_total, 1)}%`;

async function icon(Comp, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: String(size) }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";   // 13.33 × 7.5 in
pres.title = "太陽光電砍了多少樹？——以衛星樹冠分析台灣光電用地";
pres.author = "richliu / treecrowns";
const W = 13.33, H = 7.5, M = 0.6;

const txt = (slide, text, o) => slide.addText(text, { fontFace: FONT, color: C.ink, isTextBox: true, margin: 0, ...o });
function title(slide, t, sub) {
  txt(slide, t, { x: M, y: 0.4, w: W - 2 * M, h: 0.8, fontSize: 32, bold: true, color: C.forest });
  if (sub) txt(slide, sub, { x: M, y: 1.15, w: W - 2 * M, h: 0.45, fontSize: 15, color: C.muted });
}
function footer(slide, n) {
  txt(slide, `richliu.github.io/treecrowns ｜ github.com/richliu/treecrowns`, { x: M, y: H - 0.42, w: 8, h: 0.3, fontSize: 10, color: "8A958D" });
  txt(slide, String(n), { x: W - M - 0.6, y: H - 0.42, w: 0.6, h: 0.3, fontSize: 10, color: "8A958D", align: "right" });
}
function card(slide, x, y, w, h, fill = C.white) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, rectRadius: 0.12,
    line: { color: "DDE6DA", width: 0.75 }, shadow: { type: "outer", color: "000000", opacity: 0.08, blur: 6, offset: 2, angle: 90 } });
}
async function iconCircle(slide, Comp, x, y, d, bg, fg = C.white) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: bg }, line: { color: bg } });
  slide.addImage({ data: await icon(Comp, fg), x: x + d * 0.24, y: y + d * 0.24, w: d * 0.52, h: d * 0.52 });
}
const axisStyle = () => ({
  catAxisLabelColor: C.muted, valAxisLabelColor: C.muted, catAxisLabelFontFace: FONT, valAxisLabelFontFace: FONT,
  catAxisLabelFontSize: 12, valAxisLabelFontSize: 11, valGridLine: { color: "E3E8E1", size: 0.75 }, catGridLine: { style: "none" },
  legendFontFace: FONT, legendFontSize: 12, legendColor: C.ink, titleFontFace: FONT, titleColor: C.ink,
});

(async () => {
  let n = 0;
  // ===== 1. 封面 =====
  {
    const s = pres.addSlide(); n++;
    s.background = { color: C.forest };
    await iconCircle(s, fa.FaSolarPanel, M, 0.9, 1.0, C.sun, C.forest);
    await iconCircle(s, fa.FaTree, M + 1.2, 0.9, 1.0, C.leaf, C.forest);
    txt(s, "太陽光電砍了多少樹？", { x: M, y: 2.3, w: 11, h: 1.2, fontSize: 54, bold: true, color: C.white });
    txt(s, `用衛星「樹冠」分析台灣 ${BASE}–${YN} 光電用地變化`, { x: M, y: 3.55, w: 11, h: 0.6, fontSize: 24, color: C.leaf });
    txt(s, "Sentinel-2 衛星 × 農村水保署 BigGIS 植生判釋方法 × 能源署開放資料", { x: M, y: 4.3, w: 11, h: 0.5, fontSize: 16, color: "D8E6D2" });
    txt(s, "網站 richliu.github.io/treecrowns\n原始碼 github.com/richliu/treecrowns", { x: M, y: 6.1, w: 8, h: 0.8, fontSize: 13, color: "D8E6D2" });
    s.addNotes("本簡報介紹以 Sentinel-2 衛星影像估算台灣近年新增太陽光電『蓋之前是什麼地』，特別是砍了多少樹。");
  }

  // ===== 2. 理由與發想 =====
  {
    const s = pres.addSlide(); n++;
    title(s, "理由與發想", "新聞常說「光電砍樹」，但全台灣到底砍了多少？");
    const qs = [[fa.FaNewspaper, "爭議多、數字少", "「光電砍樹」「農地種電」「漁電共生」新聞不斷，但多是個案，缺少全台、逐年的客觀數字。"],
                [fa.FaSatellite, "衛星每 5 天拍一次台灣", "歐洲太空總署 Sentinel-2 免費開放 10 公尺影像，可以回頭檢查每一年的地表。"],
                [fa.FaSeedling, "政府已有現成方法", "農村水保署 BigGIS 以植生指標（NDVI）判釋森林、裸露地變化；我們沿用並擴大到全台、每年，再加上辨認太陽能板。"]];
    for (let i = 0; i < qs.length; i++) {
      const y = 1.95 + i * 1.5;
      await iconCircle(s, qs[i][0], M, y, 0.85, C.forest2);
      txt(s, qs[i][1], { x: M + 1.1, y: y - 0.02, w: 5.6, h: 0.45, fontSize: 19, bold: true });
      txt(s, qs[i][2], { x: M + 1.1, y: y + 0.45, w: 5.6, h: 0.85, fontSize: 14, color: C.muted, valign: "top" });
    }
    const cap = V.national.filter(r => r.year >= BASE);
    card(s, 7.4, 1.85, 5.35, 4.9);
    s.addChart(pres.charts.LINE, [{ name: "累計裝置容量（MW）", labels: cap.map(r => String(r.year)), values: cap.map(r => r.cap_mw) }], {
      x: 7.55, y: 2.0, w: 5.05, h: 3.6, ...axisStyle(), chartColors: [C.sun], lineSize: 3, lineDataSymbolSize: 8,
      showTitle: true, title: "全國太陽光電累計裝置容量（MW）", titleFontSize: 14, showLegend: false,
      showValue: true, dataLabelFontSize: 10, dataLabelColor: C.ink, dataLabelFormatCode: "#,##0", dataLabelPosition: "t",
      valAxisLabelFormatCode: "#,##0",
    });
    txt(s, `${BASE} 年約 ${fmt(cap[0].cap_mw / 1000, 1)} GW → ${YN} 年 ${fmt(cap[cap.length - 1].cap_mw / 1000, 1)} GW，約 ${fmt(cap[cap.length - 1].cap_mw / cap[0].cap_mw, 1)} 倍。\n這些新增的太陽能板，原本是什麼地？`,
        { x: 7.7, y: 5.65, w: 4.8, h: 0.95, fontSize: 14, bold: true, color: C.forest });
    footer(s, n);
    s.addNotes("動機：光電快速成長，爭議集中在『砍樹』，但缺乏全台尺度的量化數字。");
  }

  // ===== 3. 怎麼做 =====
  {
    const s = pres.addSlide(); n++;
    title(s, "怎麼做：四個步驟", "把台灣切成約 3.7 億個 10 公尺小格子，一年一年追蹤");
    const steps = [[fa.FaCloudSun, "每年一張無雲照片", "每年取最清楚的 15 次衛星影像，遮掉雲與雲影後取中位數，拼出全台無雲合成圖。"],
                   [fa.FaThLarge, "每一格判斷地表", "樹林（整年都綠）、農地/低植生、水、裸地/建物、太陽能板。太陽能板以台南七股、彰濱案場校正。"],
                   [fa.FaHistory, "逐年追蹤變化", `某格第一次變成太陽能板且隔年仍是＝完工年；回頭看完工前是樹、水、農地還是裸地。${BASE} 為基準年。`],
                   [fa.FaBalanceScale, "與政府資料比對", "能源署案場清單與裝置容量、山坡地、國有林、地形資料交叉檢查。"]];
    const cw = (W - 2 * M - 3 * 0.35) / 4;
    for (let i = 0; i < 4; i++) {
      const x = M + i * (cw + 0.35), y = 2.0;
      card(s, x, y, cw, 4.5);
      await iconCircle(s, steps[i][0], x + cw / 2 - 0.55, y + 0.4, 1.1, [C.forest2, C.sun, C.water, C.bare][i]);
      txt(s, `${i + 1}`, { x: x + 0.25, y: y + 0.25, w: 0.5, h: 0.5, fontSize: 22, bold: true, color: "B8C4BA" });
      txt(s, steps[i][1], { x: x + 0.25, y: y + 1.75, w: cw - 0.5, h: 0.5, fontSize: 19, bold: true, align: "center" });
      txt(s, steps[i][2], { x: x + 0.3, y: y + 2.35, w: cw - 0.6, h: 1.9, fontSize: 14, color: C.muted, valign: "top" });
      if (i < 3) s.addShape(pres.shapes.RIGHT_TRIANGLE, { x: x + cw + 0.08, y: y + 0.8, w: 0.2, h: 0.3, rotate: 90, fill: { color: "B8C4BA" }, line: { color: "B8C4BA" } });
    }
    footer(s, n);
    s.addNotes("方法依據：BigGIS Sentinel-2 影像變異分析的 NDVI/SI/Gn 決策樹；太陽能板以短波紅外與近紅外的光譜差辨識。");
  }

  // ===== 4. 資料來源 =====
  {
    const s = pres.addSlide(); n++;
    title(s, "資料來源", "全部使用公開、免費的資料與開源工具");
    const src = [[fa.FaSatellite, "Sentinel-2 L2A 衛星影像", "歐洲太空總署 Copernicus；AWS Open Data（Element84 Earth Search）。2017–2025，每年 19 個圖幅，約 30 GB 合成影像。"],
                 [fa.FaLeaf, "BigGIS 植生判釋方法", "農業部農村發展及水土保持署「Sentinel-2 影像變異分析」：NDVI、陰影、綠度指標決策樹。"],
                 [fa.FaSolarPanel, "能源署光電資料", `電業級案場地號清單（${V.towns.plants_n} 案、${fmt(V.towns.plants_land_ha)} 公頃）、各縣市同意備案、全國裝置容量年資料。`],
                 [fa.FaMountain, "山坡地與國有林", "農村水保署 115 年山坡地範圍圖（非六都）、林業保育署國有林事業區圖。"],
                 [fa.FaRulerCombined, "地形", "Copernicus DEM 30 公尺數值地表模型，推估標高與坡度。"],
                 [fa.FaMapMarkedAlt, "底圖與行政界", "國土測繪中心正射影像（目視抽查）、內政部縣市 / 鄉鎮界。"]];
    const cw = (W - 2 * M - 2 * 0.35) / 3, ch = 2.35;
    for (let i = 0; i < 6; i++) {
      const x = M + (i % 3) * (cw + 0.35), y = 1.9 + Math.floor(i / 3) * (ch + 0.3);
      card(s, x, y, cw, ch);
      await iconCircle(s, src[i][0], x + 0.3, y + 0.3, 0.75, C.forest2);
      txt(s, src[i][1], { x: x + 1.25, y: y + 0.35, w: cw - 1.45, h: 0.65, fontSize: 17, bold: true, valign: "middle" });
      txt(s, src[i][2], { x: x + 0.3, y: y + 1.2, w: cw - 0.6, h: 1.0, fontSize: 13, color: C.muted, valign: "top" });
    }
    footer(s, n);
  }

  // ===== 5. 單位 =====
  {
    const s = pres.addSlide(); n++;
    title(s, "先認識單位：「公頃」有多大？", "本簡報的面積都用公頃（hectare，縮寫 ha）");
    card(s, M, 1.9, 5.2, 4.8, C.paper);
    s.addShape(pres.shapes.RECTANGLE, { x: M + 1.1, y: 2.3, w: 3.0, h: 3.0, fill: { color: C.leaf }, line: { color: C.forest2, width: 2 } });
    txt(s, "1 公頃", { x: M + 1.1, y: 3.35, w: 3.0, h: 0.8, fontSize: 36, bold: true, color: C.forest, align: "center" });
    txt(s, "100 公尺", { x: M + 1.1, y: 5.4, w: 3.0, h: 0.4, fontSize: 14, color: C.muted, align: "center" });
    txt(s, "100 公尺", { x: M + 4.2, y: 3.6, w: 1.0, h: 0.4, fontSize: 14, color: C.muted });
    txt(s, "= 10,000 平方公尺", { x: M, y: 5.95, w: 5.2, h: 0.5, fontSize: 18, bold: true, align: "center" });
    const eqs = [[fa.FaHome, "≈ 3,025 坪", "約 100 間 30 坪的房子"], [fa.FaTractor, "≈ 1.03 甲", "台灣農地常用的「甲」，幾乎一樣大"],
                 [fa.FaFutbol, "≈ 1.4 個足球場", "標準足球場 105 × 68 公尺"], [fa.FaTree, "大安森林公園 ≈ 26 公頃", "本簡報常用它當比較單位"]];
    for (let i = 0; i < 4; i++) {
      const y = 1.95 + i * 1.2;
      await iconCircle(s, eqs[i][0], 6.3, y, 0.85, [C.sun, C.farm, C.water, C.forest2][i]);
      txt(s, eqs[i][1], { x: 7.4, y: y, w: 5.3, h: 0.5, fontSize: 22, bold: true });
      txt(s, eqs[i][2], { x: 7.4, y: y + 0.5, w: 5.3, h: 0.4, fontSize: 14, color: C.muted });
    }
    footer(s, n);
  }

  // ===== 6. 結果總覽 =====
  {
    const s = pres.addSlide(); n++;
    title(s, `結果總覽：${BASE + 1}–${YN} 新增的太陽能板，原本是什麼？`, `全台新增 ${fmt(T.pv_new_total)} 公頃（${eq(T.pv_new_total)}）；${BASE} 年以前已存在 ${fmt(T.pv_existing_baseline)} 公頃`);
    const rows = [["farm", "農地 / 低植生", "約一半，最多"], ["water", "水體（魚塭 / 鹽田 / 埤塘）", "漁電共生、水面型"],
                  ["bare", "裸露地 / 建物", "含整地、乾鹽田、工業區"], ["tree", "樹林（砍樹光電）", `含空窗多年再蓋 ${fmt(TIERS[1].cum)}，最寬 ${fmt(TMAX)} 公頃`]];
    for (let i = 0; i < 4; i++) {
      const [k, name, note] = rows[i], col = C[k], y = 1.95 + i * 1.2;
      card(s, M, y, 7.3, 1.05);
      s.addShape(pres.shapes.OVAL, { x: M + 0.25, y: y + 0.3, w: 0.45, h: 0.45, fill: { color: col }, line: { color: col } });
      txt(s, name, { x: M + 0.9, y: y + 0.12, w: 3.3, h: 0.45, fontSize: 17, bold: true });
      txt(s, note, { x: M + 0.9, y: y + 0.55, w: 3.3, h: 0.4, fontSize: 12, color: C.muted });
      txt(s, `${fmt(P[k])} 公頃`, { x: M + 4.2, y: y + 0.08, w: 2.9, h: 0.55, fontSize: 26, bold: true, color: col, align: "right" });
      txt(s, `${pct(P[k])}　${eq(P[k])}`, { x: M + 3.6, y: y + 0.6, w: 3.5, h: 0.35, fontSize: 12, color: C.muted, align: "right" });
    }
    card(s, 8.2, 1.95, 4.55, 4.65);
    s.addChart(pres.charts.DOUGHNUT, [{ name: "前身", labels: rows.map(r => r[1]), values: rows.map(r => P[r[0]]) }], {
      x: 8.3, y: 2.05, w: 4.35, h: 4.45, chartColors: rows.map(r => C[r[0]]), holeSize: 55,
      showPercent: true, showValue: false, showLegend: true, legendPos: "b", legendFontFace: FONT, legendFontSize: 11,
      dataLabelColor: C.white, dataLabelFontSize: 12, dataLabelFontBold: true,
    });
    footer(s, n);
    s.addNotes("前身判斷：完工前多數年份是樹 → 樹林；1/3 以上年份是水 → 水體；其餘看農地/裸地何者多。");
  }

  // ===== 7. 逐年 =====
  {
    const s = pres.addSlide(); n++;
    const tot = y => Object.values(T.pred_install[y]).reduce((a, b) => a + b, 0);
    const late = NEWY.filter(y => +y >= 2021).map(tot);
    title(s, "每年新增多少？", `依「蓋之前是什麼」分色（公頃）；2021 年起每年新增約 ${fmt(Math.min(...late))}–${fmt(Math.max(...late))} 公頃`);
    s.addChart(pres.charts.BAR, PRED.map(([k, name]) => ({ name, labels: NEWY, values: NEWY.map(y => T.pred_install[y][k]) })), {
      x: M, y: 1.8, w: 8.4, h: 5.0, barDir: "col", barGrouping: "stacked", ...axisStyle(),
      chartColors: PRED.map(p => p[2]), showLegend: true, legendPos: "b", valAxisLabelFormatCode: "#,##0",
      showValue: false, valAxisTitle: "公頃", showValAxisTitle: true, valAxisTitleFontSize: 12, valAxisTitleColor: C.muted,
    });
    const peakTree = NEWY.reduce((a, y) => T.pred_install[y].tree > T.pred_install[a].tree ? y : a, NEWY[0]);
    const early = NEWY.filter(y => +y < 2021).map(tot);
    const waterTop = [...NEWY].sort((a, b) => T.pred_install[b].water - T.pred_install[a].water).slice(0, 3).sort();
    const pts = [`${NEWY[0]}–2020 每年約 ${fmt(Math.min(...early))}–${fmt(Math.max(...early))} 公頃，2021 起倍增`,
                 `水體（藍）在 ${waterTop.join("、")} 年特別多：漁電共生、彰濱水面型`,
                 `砍樹光電（紅）每年都很少，最多是 ${peakTree} 年的 ${fmt(T.pred_install[peakTree].tree)} 公頃`,
                 `${YN} 年只有一年觀測，尚待隔年確認`];
    card(s, 9.3, 1.9, 3.45, 4.8, C.paper);
    txt(s, pts.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < pts.length - 1 } })),
        { x: 9.5, y: 2.1, w: 3.05, h: 4.4, fontSize: 14, paraSpaceAfter: 10, valign: "top" });
    footer(s, n);
  }

  // ===== 8. 縣市 =====
  {
    const s = pres.addSlide(); n++;
    const cs = [...S.counties].sort((a, b) => b.pv_new_total - a.pv_new_total).slice(0, 10).reverse();
    title(s, "哪些縣市最多？", `前 10 名縣市新增光電（${BASE + 1}–${YN}，公頃），依前身分色`);
    s.addChart(pres.charts.BAR, PRED.map(([k, name]) => ({ name, labels: cs.map(c => c.name), values: cs.map(c => c.pred_total[k]) })), {
      x: M, y: 1.8, w: 8.4, h: 5.1, barDir: "bar", barGrouping: "stacked", ...axisStyle(),
      chartColors: PRED.map(p => p[2]), showLegend: true, legendPos: "b", valAxisLabelFormatCode: "#,##0",
    });
    const top = [...S.counties].sort((a, b) => b.pv_new_total - a.pv_new_total);
    const treeTop = [...S.counties].sort((a, b) => b.pred_total.tree - a.pred_total.tree).slice(0, 2);
    const t0 = top[0].pred_total;
    const pts = [`${top[0].name}最多（${fmt(top[0].pv_new_total)} 公頃），以農地為主（${fmt(t0.farm)}）、魚塭次之（${fmt(t0.water)}）`,
                 `彰化以水體為主：彰濱工業區、鹿港濱海水面型光電`,
                 `嘉義、雲林以農地 / 低植生為主`,
                 `砍樹光電最多的是${treeTop[0].name}（${fmt(treeTop[0].pred_total.tree)} 公頃）與${treeTop[1].name}（${fmt(treeTop[1].pred_total.tree)} 公頃）`];
    card(s, 9.3, 1.9, 3.45, 4.8, C.paper);
    txt(s, pts.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < pts.length - 1 } })),
        { x: 9.5, y: 2.1, w: 3.05, h: 4.4, fontSize: 14, paraSpaceAfter: 10, valign: "top" });
    footer(s, n);
  }

  // ===== 9. 衛星前後對照 =====
  {
    const s = pres.addSlide(); n++;
    title(s, "衛星看得到的改變", `同一地點 ${BASE} 年（上）vs ${YN} 年（下）｜本研究 Sentinel-2 年度去雲合成影像（ESA Copernicus），10 公尺解析度`);
    const ex = [["hualien_tree", "樹林 → 光電", "花蓮鳳林（約 34 公頃）", C.tree],
                ["changbin_water", "水面 → 光電", "彰化鹿港 彰濱（約 318 公頃）", C.water],
                ["qigu_farm", "農地 → 光電", "台南七股（約 62 公頃）", C.farm]];
    const cw = (W - 2 * M - 2 * 0.35) / 3, iw = 2.05;
    for (let i = 0; i < 3; i++) {
      const x = M + i * (cw + 0.35), y = 1.75;
      s.addShape(pres.shapes.OVAL, { x, y: y + 0.08, w: 0.32, h: 0.32, fill: { color: ex[i][3] }, line: { color: ex[i][3] } });
      txt(s, ex[i][1], { x: x + 0.45, y, w: cw - 0.45, h: 0.45, fontSize: 19, bold: true });
      txt(s, ex[i][2], { x: x + 0.45, y: y + 0.45, w: cw - 0.45, h: 0.35, fontSize: 13, color: C.muted });
      for (let j = 0; j < 2; j++) {
        const yr = j ? YN : BASE, iy = y + 0.95 + j * (iw + 0.1), ix = x + cw - iw - 0.1;
        s.addImage({ path: path.join(__dirname, "img", `${ex[i][0]}_${yr}.png`), x: ix, y: iy, w: iw, h: iw });
        txt(s, String(yr), { x: x + 0.45, y: iy + iw / 2 - 0.25, w: ix - x - 0.6, h: 0.5, fontSize: 20, bold: true,
                             color: j ? ex[i][3] : "8A958D", align: "right" });
      }
    }
    footer(s, n);
  }

  // ===== 10. 砍樹光電在哪裡 =====
  {
    const s = pres.addSlide(); n++;
    title(s, "砍樹光電在哪裡？", `原為樹林面積最大的案場（已排除只在 ${YN} 年出現、尚未確認者）`);
    const top = SITES.filter(p => p.year > BASE && p.year < YN && p.tree_frac >= 0.3).sort((a, b) => b.tree_ha - a.tree_ha).slice(0, 8);
    const hdr = ["縣市", "鄉鎮", "完工年", "原為樹林（公頃）", "標高（m）"].map(t => ({ text: t, options: { bold: true, color: C.white, fill: { color: C.forest } } }));
    const body = top.map(p => [p.county, p.town || "", String(p.year), fmt(p.tree_ha, 1), p.elev == null ? "" : fmt(p.elev)]);
    s.addTable([hdr, ...body], { x: M, y: 1.85, w: 7.2, colW: [1.3, 1.4, 1.1, 2.0, 1.4], fontFace: FONT, fontSize: 13, color: C.ink,
      border: { type: "solid", color: "DDE6DA", pt: 0.75 }, rowH: 0.48, align: "center", valign: "middle" });
    const bt = V.sites.by_terrain;
    const kp = [[fa.FaMapMarkerAlt, "集中在花蓮、屏東", "最大一處是花蓮鳳林、光復一帶的平地造林地；屏東分散在佳冬、車城、恆春、獅子等地。"],
                [fa.FaMountain, "多在平地，不在山坡", `平地原為樹林 ${fmt(bt.flat.tree)} 公頃，山坡地僅 ${fmt(bt.slopeland.tree)} 公頃（DEM 推估）。`],
                [fa.FaTree, "國有林內極少", `位於國有林事業區的新增光電 ${bt.nat_forest.n} 處、${fmt(bt.nat_forest.area)} 公頃，原為樹林僅 ${fmt(bt.nat_forest.tree, 1)} 公頃。`]];
    for (let i = 0; i < 3; i++) {
      const y = 1.85 + i * 1.6;
      await iconCircle(s, kp[i][0], 8.3, y, 0.75, C.tree);
      txt(s, kp[i][1], { x: 9.25, y, w: 3.5, h: 0.45, fontSize: 17, bold: true });
      txt(s, kp[i][2], { x: 9.25, y: y + 0.45, w: 3.5, h: 1.05, fontSize: 13, color: C.muted, valign: "top" });
    }
    footer(s, n);
  }

  // ===== 10b. 先砍樹、空窗、再蓋 =====
  {
    const s = pres.addSlide(); n++;
    title(s, "先砍樹、空窗幾年、再蓋光電？", "逐年追蹤每一格：把「空窗期較長」的情況也算進來，砍樹光電有多少？");
    card(s, M, 1.85, 6.3, 3.05);
    s.addChart(pres.charts.BAR, [{ name: "累計（公頃）", labels: TIERS.map(t => t.l), values: TIERS.map(t => Math.round(t.cum)) }], {
      x: M + 0.1, y: 1.95, w: 6.1, h: 2.85, barDir: "bar", ...axisStyle(), catAxisOrientation: "maxMin",
      chartColors: ["DC003C"], showLegend: false, showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 12,
      dataLabelColor: C.ink, dataLabelFormatCode: "#,##0", valAxisHidden: true, valGridLine: { style: "none" },
      showTitle: true, title: "砍樹光電（逐層累加，公頃）", titleFontSize: 13, catAxisLabelFontSize: 12,
    });
    const gy = Object.keys(TP.cleared_gap_years);
    card(s, M, 5.05, 6.3, 1.85);
    s.addChart(pres.charts.BAR, [{ name: "面積（公頃）", labels: gy.map(g => `${g} 年`), values: gy.map(g => TP.cleared_gap_years[g]) }], {
      x: M + 0.1, y: 5.1, w: 3.6, h: 1.75, barDir: "col", ...axisStyle(), chartColors: [C.bare], showLegend: false,
      showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 10, dataLabelFormatCode: "0.0", valAxisHidden: true,
      valGridLine: { style: "none" }, showTitle: true, title: "空窗幾年才蓋", titleFontSize: 12, catAxisLabelFontSize: 10,
    });
    const bc = TP.cleared_between_classes;
    txt(s, [{ text: "空窗期間多是", options: { breakLine: true, fontSize: 12, color: C.muted } },
            { text: `低植生 ${bc["低植生"] ?? 0}%`, options: { breakLine: true, fontSize: 16, bold: true, color: C.farm } },
            { text: `裸露地 ${bc["裸露地/建物"] ?? 0}%`, options: { fontSize: 16, bold: true, color: C.bare } }],
        { x: M + 3.85, y: 5.35, w: 2.3, h: 1.3, valign: "middle" });
    const iw = 1.42, x0 = 7.25;
    txt(s, "例：桃園（24.931, 121.186）", { x: x0, y: 1.85, w: 5.5, h: 0.4, fontSize: 16, bold: true });
    const cap = { 2018: "樹林", 2020: "整地", 2022: "蓋工廠", 2024: "屋頂光電" };
    [2018, 2020, 2022, 2024].forEach((y, j) => {
      s.addImage({ path: path.join(__dirname, "img", `taoyuan_cleared_${y}.png`), x: x0 + j * (iw + 0.08), y: 2.35, w: iw, h: iw });
      txt(s, `${y} ${cap[y]}`, { x: x0 + j * (iw + 0.08), y: 2.35 + iw + 0.05, w: iw, h: 0.35, fontSize: 12, bold: true, align: "center",
                                 color: y === 2024 ? C.tree : C.muted });
    });
    card(s, x0, 4.4, 5.5, 2.5, C.paper);
    const pts = [`不含空窗的嚴格數字 ${fmt(TIERS[0].cum)} 公頃；加上「先砍樹、空窗多年再蓋」約 ${fmt(TIERS[1].cum)} 公頃`,
                 `空窗多為 3–6 年，期間多半長回草或短期耕作`,
                 `但原因看不到：像桃園這塊，樹是為了蓋工廠砍的，光電是之後裝在屋頂`,
                 `全部算進去最多約 ${fmt(TMAX)} 公頃，仍不到新增光電的 6%`];
    txt(s, pts.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < pts.length - 1 } })),
        { x: x0 + 0.2, y: 4.55, w: 5.1, h: 2.25, fontSize: 13, paraSpaceAfter: 6, valign: "top" });
    footer(s, n);
    s.addNotes("路徑分析：多數年份是樹＝主要數字；≥2 年是樹、之後到完工都不是樹＝先砍樹空窗再蓋；只有 2017 是樹＝基準年前已砍；只有 1 年是樹＝證據弱。");
  }

  // ===== 11. 可信度 =====
  {
    const s = pres.addSlide(); n++;
    title(s, "結果可信嗎？和政府資料比一比", "衛星偵測面積與能源署統計的趨勢一致");
    const nat = V.national.filter(r => r.year >= BASE);
    card(s, M, 1.85, 7.6, 4.95);
    s.addChart([{ type: pres.charts.BAR, data: [{ name: "衛星偵測光電面積（公頃）", labels: nat.map(r => String(r.year)), values: nat.map(r => r.det_pv) }],
                  options: { chartColors: ["7B2CBF"], barGapWidthPct: 60 } },
                { type: pres.charts.LINE, data: [{ name: "能源署累計裝置容量（MW）", labels: nat.map(r => String(r.year)), values: nat.map(r => r.cap_mw) }],
                  options: { chartColors: [C.sun], lineSize: 3, lineDataSymbolSize: 7, secondaryValAxis: true, secondaryCatAxis: true } }], {
      x: M + 0.15, y: 2.0, w: 7.3, h: 4.65, ...axisStyle(), showLegend: true, legendPos: "b",
      valAxes: [{ showValAxisTitle: true, valAxisTitle: "公頃", valAxisLabelFormatCode: "#,##0", valAxisTitleColor: C.muted },
                { showValAxisTitle: true, valAxisTitle: "MW", valAxisLabelFormatCode: "#,##0", valAxisTitleColor: C.muted, valGridLine: { style: "none" } }],
      catAxes: [{ catAxisTitle: "年" }, { catAxisHidden: true }],
    });
    const stats = [[`r = ${V.towns.corr.toFixed(2)}`, `鄉鎮層級：能源署 ${V.towns.plants_n} 個大型案場土地 vs 衛星偵測面積的相關係數`],
                   [`${Math.round(100 * V.towns.det_in_plant_towns / V.towns.det_total)}%`, "衛星偵測的新增光電，落在有能源署大型案場的鄉鎮"],
                   ["75–90%", "航照抽查：大型案場內被偵測到的比例"]];
    for (let i = 0; i < 3; i++) {
      const y = 1.9 + i * 1.65;
      card(s, 8.55, y, 4.2, 1.45, C.paper);
      txt(s, stats[i][0], { x: 8.8, y: y + 0.12, w: 3.8, h: 0.65, fontSize: 30, bold: true, color: C.forest });
      txt(s, stats[i][1], { x: 8.8, y: y + 0.78, w: 3.8, h: 0.6, fontSize: 12, color: C.muted, valign: "top" });
    }
    footer(s, n);
    s.addNotes("累計裝置容量含屋頂型，衛星看不到屋頂型，所以面積與容量不會等比，但趨勢同步。");
  }

  // ===== 12. 研究限制 =====
  {
    const s = pres.addSlide(); n++;
    title(s, "研究限制", "解讀數字時請一起考慮");
    const lim = [[fa.FaHome, "看不到屋頂與小型光電", "一格 10 公尺，0.2 公頃以下與屋頂型大多抓不到，光電面積是「下限」。"],
                 [fa.FaTree, "「樹」的定義影響結果", `嚴格 ${fmt(P.tree)} 公頃；含空窗多年再蓋、寬鬆定義最多約 ${fmt(TMAX)} 公頃；且看不到砍樹原因（如砍樹蓋工廠）。`],
                 [fa.FaWater, "農地類別較粗", "「農地/低植生」也包含草生地、海埔地與長藻的魚塭，水體比例可能偏低。"],
                 [fa.FaCalendarAlt, "2017 只當參考", `2017 年只有一顆衛星、觀測少、樹林低估，統計從 ${BASE} 年開始；${YN} 年新案場尚待隔年確認。`],
                 [fa.FaMapPin, "無法逐案對到政府案場", "能源署清單只有地號、沒有公開座標，只能以鄉鎮比對。"],
                 [fa.FaMountain, "山坡地為推估", "以 30 公尺地形模型依法定定義推估；六都官方山坡地圖未開放下載。"]];
    const cw = (W - 2 * M - 0.4) / 2;
    for (let i = 0; i < 6; i++) {
      const x = M + (i % 2) * (cw + 0.4), y = 1.85 + Math.floor(i / 2) * 1.6;
      await iconCircle(s, lim[i][0], x, y, 0.75, C.bare);
      txt(s, lim[i][1], { x: x + 0.95, y, w: cw - 1.0, h: 0.45, fontSize: 17, bold: true });
      txt(s, lim[i][2], { x: x + 0.95, y: y + 0.45, w: cw - 1.0, h: 0.95, fontSize: 13, color: C.muted, valign: "top" });
    }
    footer(s, n);
  }

  // ===== 13. 結論 =====
  {
    const s = pres.addSlide(); n++;
    s.background = { color: C.forest };
    txt(s, "結論", { x: M, y: 0.5, w: 6, h: 0.8, fontSize: 38, bold: true, color: C.white });
    const cons = [[`${fmt(T.pv_new_total)} 公頃`, `${BASE + 1}–${YN} 新增太陽能板，${eq(T.pv_new_total)}`],
                  [`${pct(P.farm + P.water)}`, "蓋在農地與魚塭、鹽田等水面：光電的主要用地議題是「農地」與「漁電」"],
                  [`${fmt(P.tree)} 公頃（${pct(P.tree)}）`, `原本是樹林，${eq(P.tree)}；含先砍樹空窗多年再蓋、寬鬆定義，最多約 ${fmt(TMAX)} 公頃（< 6%）`],
                  ["局部而非全面", "砍樹光電集中在花蓮、屏東少數案場，多在平地；值得逐案檢視，但「全台大規模砍樹」不成立"]];
    for (let i = 0; i < 4; i++) {
      const y = 1.55 + i * 1.28;
      txt(s, cons[i][0], { x: M, y, w: 4.4, h: 0.7, fontSize: 28, bold: true, color: i === 2 ? "FFB3C1" : C.sun });
      txt(s, cons[i][1], { x: M + 4.6, y: y + 0.05, w: 7.5, h: 0.95, fontSize: 16, color: C.white, valign: "top" });
    }
    txt(s, "下一步：區分優良農地 / 一般農地、魚塭 / 鹽田；取得案場座標做逐案驗證；以高解析航照補屋頂型光電。",
        { x: M, y: 6.45, w: W - 2 * M, h: 0.4, fontSize: 13, color: "D8E6D2" });
    txt(s, "richliu.github.io/treecrowns ｜ github.com/richliu/treecrowns", { x: M, y: 6.9, w: 8, h: 0.35, fontSize: 12, color: C.leaf });
  }

  const out = path.join(ROOT, "public", "slides", "treecrowns.pptx");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  await pres.writeFile({ fileName: out });
  console.log("wrote", out);
})();
