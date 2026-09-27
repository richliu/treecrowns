# treecrowns — 太陽光電砍了多少樹？

用 Sentinel-2 衛星影像與樹冠（植生）分析，估算台灣 2018–2025 年新增的太陽光電「蓋之前是什麼地」，特別是砍了多少樹。

- 網站：<https://richliu.github.io/treecrowns/>
- 白話說明：[成果說明](https://richliu.github.io/treecrowns/about.html)
- 簡報：[treecrowns.pptx](https://richliu.github.io/treecrowns/slides/treecrowns.pptx)

> 單位：**1 公頃 = 10,000 平方公尺（100 m × 100 m）≈ 3,025 坪 ≈ 1.03 甲 ≈ 1.4 個標準足球場**；台北大安森林公園約 26 公頃。

## 主要結果（2019–2025，以 2018 為基準年）

| 新增太陽能板蓋之前是 | 面積 | 佔新增 |
|---|---:|---:|
| 農地 / 低植生 | 1,912 公頃 | 49.5% |
| 水體（魚塭 / 鹽田 / 埤塘） | 1,201 公頃 | 31.1% |
| 裸露地 / 建物 | 659 公頃 | 17.0% |
| 樹林（砍樹光電） | 94 公頃 | 2.4% |
| **合計** | **3,866 公頃**（≈ 149 座大安森林公園） | |

- 若把果園、檳榔、竹林也算「樹」，砍樹光電約 180 公頃；任何植被約 405 公頃。
- 砍樹光電集中在花蓮（鳳林、光復一帶平地造林地）與屏東，多數在平地而非山坡地。
- 與經濟部能源署 419 個電業級案場比對，鄉鎮層級相關係數 r = 0.79；偵測面積成長與全國累計裝置容量同步。

## 方法

1. **年度去雲合成**：每個 Sentinel-2 圖幅每年取雲量最低 15 景，以 SCL 遮雲後取中位數（10 m）。
2. **分類**：參考農業部農村發展及水土保持署 BigGIS〈Sentinel-2 影像變異分析〉的 NDVI / 陰影 / 綠度決策樹，
   分出樹冠、低植生、裸露地、水體、陰影；太陽能板以 `NDVI 低 且 (B11−B8)/(B11+B8) > 0.3` 等光譜規則辨識，以台南七股、彰濱案場校正。
3. **逐像元時間序列**：完工年 = 第一次為太陽能板且隔年仍是；前身 = 完工前各年：樹冠過半 → 樹；水體 ≥ 1/3 → 水；其餘看農地 / 裸露地何者多。
4. **驗證與套疊**：能源署案場（鄉鎮比對）、同意備案 / 裝置容量、山坡地範圍、國有林事業區、Copernicus DEM。

詳見網站「方法與限制」「驗證與圖資」頁。

## 研究限制

- 10 m 解析度看不到屋頂型與 0.2 公頃以下案場，光電面積為下限。
- 「樹」的定義影響結果（另提供寬鬆定義）；「農地 / 低植生」可能含草生地、海埔地與長藻魚塭。
- 2017 年只有 Sentinel-2A、觀測少、樹冠低估，只當參考；2025 年新案場尚待隔年確認。
- 能源署案場只有地號、無公開座標，只能以鄉鎮比對；六都官方山坡地圖未開放下載，以 DEM 推估。

## 目錄

```
pipeline/
  composite.py        年度去雲中位數合成（每 MGRS tile）
  classify.py         分類（樹冠 / 低植生 / 裸露地 / 水體 / 陰影 / 太陽能板）
  timeseries.py       逐像元時間序列：完工年、前身、樹冠消失 → data/stats/timeseries.json
  sensitivity.py      砍樹光電的定義敏感度
  overlay.py          外部圖資套疊與驗證 → data/stats/validation.json
  tiles.py            XYZ 圖磚
  build_site.py       Jinja2 模板 → public/
  run_years.sh        逐年合成 + 分類
  run_post.sh         分類 → 統計 → 套疊 → 圖磚 → 網站
  deploy_pages.sh     發佈 public/ 到 GitHub Pages（gh-pages 分支）
site/templates/       網站模板（Bootstrap 5、Leaflet、Chart.js、simple-datatables）
slides-src/build.js   成果簡報產生器（pptxgenjs）
```

## 重現

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
pipeline/run_years.sh 2017 2018 2019 2020 2021 2022 2023 2024 2025   # 下載與合成，約 30 GB，需數小時
pipeline/run_post.sh  2017 2018 2019 2020 2021 2022 2023 2024 2025
(cd slides-src && npm install && node build.js)                      # 簡報
pipeline/deploy_pages.sh                                              # 發佈
```

外部資料（能源署案場地號、同意備案 PDF、山坡地、國有林、DEM）放在 `data/ext/`，下載來源見網站「驗證與圖資」頁。

## 資料來源與授權

- Copernicus Sentinel-2 L2A（ESA），經 AWS Open Data / Element84 Earth Search
- 農業部農村發展及水土保持署 BigGIS（方法）、115 年度山坡地範圍圖
- 農業部林業及自然保育署 國有林事業區圖
- 經濟部能源署 太陽光電案場地號、同意備案、再生能源裝置容量（政府資料開放授權條款）
- Copernicus DEM GLO-30；內政部國土測繪中心 正射影像與電子地圖（底圖）；縣市 / 鄉鎮界：taiwan-atlas

本專案為實驗性分析，數據僅供參考。
