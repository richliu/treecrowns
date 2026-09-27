"""共用設定：路徑、GDAL 環境、縣市界、tile 清單。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BOUNDARY = DATA / "boundary" / "counties.geojson"
COMPOSITE_DIR = DATA / "composite"
CLASS_DIR = DATA / "class"
PUBLIC = ROOT / "public"

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"

# 本島用 UTM 51 的 tile（優先），澎湖 / 金門 / 本島西緣補洞用 UTM 50 的 tile
TILES_PRIMARY = ["51QTE", "51QTF", "51QTG", "51QUE", "51QUF", "51QUG",
                 "51RTH", "51RUH", "51RUJ", "51RTK"]
TILES_SECONDARY = ["50QRK", "50QRL", "50QRM", "50RRN", "50RRP", "50RPN", "50QQM",
                   "50QQL", "50QPM", "50RQN", "50RQP", "50RQQ"]   # 澎湖南方、金門、馬祖小島

# 輸出 composite 的 band 順序
BANDS_OUT = ["B02", "B03", "B04", "B08", "B11", "NDVI_MED", "NDVI_P25", "COUNT"]
STAC_ASSET = {"B02": "blue", "B03": "green", "B04": "red", "B08": "nir",
              "B11": "swir16", "SCL": "scl"}

# 保留的 SCL 類別：2 暗區(含地形陰影) 4 植生 5 非植生 6 水體 7 未分類
SCL_VALID = (2, 4, 5, 6, 7)

GDAL_ENV = dict(
    AWS_NO_SIGN_REQUEST="YES",
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
    GDAL_HTTP_MULTIPLEX="YES",
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
    GDAL_HTTP_MAX_RETRY="5",
    GDAL_HTTP_RETRY_DELAY="2",
    VSI_CACHE="TRUE",
    VSI_CACHE_SIZE=str(64 * 1024 * 1024),
    GDAL_CACHEMAX="512",
)


def set_gdal_env():
    for k, v in GDAL_ENV.items():
        os.environ.setdefault(k, v)


def load_counties():
    import geopandas as gpd
    return gpd.read_file(BOUNDARY).set_crs(4326, allow_override=True)
