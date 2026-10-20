# Notebook Usage

The notebook `MS_Calibration_Panel_EN_module.ipynb` calls the module in the following order.
Settings are defined in the first cell; all processing happens in the module.

## 1. Settings

```python
# ---- Input -------------------------------------------------------------------
# Any image of the capture is enough – the other 3 bands are found automatically
IMAGE_PATH = "DJI_20260820154930_0016_MS_G.TIF"

# ---- Reflectance calibration (ELM) -------------------------------------------
# "1-point": first panel only, line through the origin
# "2-point": all panels below, line with offset (with 3+ panels also R²)
ELM_MODE = "1-point"

# Reflectance of YOUR panels per band (0.0–1.0), from the calibration certificate.
# G = 560 nm, R = 650 nm, RE = 730 nm, NIR = 860 nm
# With the 1-point method only the FIRST panel is used.
PANELS = {
    "bright": {"G": 0.513, "R": 0.512, "RE": 0.511, "NIR": 0.509},
    "dark":   {"G": 0.05,  "R": 0.05,  "RE": 0.05,  "NIR": 0.05},   # placeholder!
}

MAX_SATURATION_PERCENT = 1.0  # panel with more saturated pixels is not used in that band
EDGE_FRACTION = 0.10          # shrink panel polygon by 10 % per side (edges, mixed pixels)

# ---- Processing --------------------------------------------------------------
REFERENCE_BAND = "R"          # other bands are aligned to this band via ECC
QUALITY_FILTER = True         # False = also process images without RTK Fixed / SurveyingMode

# ---- Georeferencing with GCPs (optional) -------------------------------------
USE_GCPS = True
GCP_CSV = "lwi_try.csv"       # RTK rover export (e.g. Emlid Flow): Name, Longitude, Latitude, ...
GCP_UTM_ZONE = None           # None = automatic from longitude (Germany: 32 or 33)
GEOREF_TRANSFORM = "homography"   # "homography" (≥4 points) or "affine" (≥3 points)
CHECK_POINTS = []             # GCPs used ONLY for accuracy check, e.g. ["6"]
OUTPUT_RESOLUTION = None      # output pixel size in m, None = same as image (GSD)
OUTPUT_DIR = "output"

# ---- System ------------------------------------------------------------------
EXIFTOOL_PATH = None          # only if Jupyter cannot find exiftool ("which exiftool")
```

| Setting | Meaning |
|---|---|
| `ELM_MODE` | `"1-point"` (first panel only, $b = 0$) or `"2-point"` (all panels, line with offset). |
| `PANELS` | Certified reflectance per panel and band. The **first** entry is used for 1-point. |
| `MAX_SATURATION_PERCENT` | A panel with more saturated pixels is dropped for that band. |
| `EDGE_FRACTION` | Polygon shrink per side (excludes edge/mixed pixels). |
| `REFERENCE_BAND` | Target band for ECC alignment and for clicking GCPs. |
| `QUALITY_FILTER` | Skip captures without RTK Fixed / SurveyingMode 1. |
| `CHECK_POINTS` | GCP names excluded from the fit and used only for independent accuracy. |

## 2. Load the module

```python
%load_ext autoreload
%autoreload 2

import os
import numpy as np
import cv2
import matplotlib.pyplot as plt

import m3m_processing as m3m
from m3m_processing import *          # all functions + BANDS, SATURATION_DN

m3m.configure(REFERENCE_BAND=REFERENCE_BAND, QUALITY_FILTER=QUALITY_FILTER,
              EXIFTOOL_PATH=EXIFTOOL_PATH, GCP_UTM_ZONE=GCP_UTM_ZONE)
```

## 3. Steps 0–7: load and correct the capture

```python
capture = load_capture(IMAGE_PATH)

# Access e.g.:
# capture["dn"]["NIR"]        corrected NIR band (DN/s)
# capture["valid"]["R"]       mask: valid pixels in the red band
# capture["tags"]["RE"]       metadata of the red edge image

show_bands(capture, kind="raw")         # unprocessed: exact saturation, black level visible
show_bands(capture, kind="corrected")   # after black level, normalisation, vignetting, geometry, ECC

position = camera_position(capture)
# show_position_tags(capture)   # lists all position-related metadata entries
```

## 4. Step 8: mark the panel(s)

```python
to_mark = list(PANELS)[:1] if ELM_MODE == "1-point" else list(PANELS)

PANEL_POLYGONS = {}
for name in to_mark:
    PANEL_POLYGONS[name] = mark_panel(capture, band="NIR", name=name)

# alternatively by hand: corners (x, y) per panel
# PANEL_POLYGONS = {
#     "bright": [(1200, 800), (1238, 806), (1232, 844), (1194, 838)],
#     "dark":   [(1500, 900), (1538, 906), (1532, 944), (1494, 938)],
# }

PANEL_POLYGONS_INNER = {n: shrink_polygon(p, EDGE_FRACTION) for n, p in PANEL_POLYGONS.items()}
for n in PANEL_POLYGONS:
    show_polygon(capture, PANEL_POLYGONS_INNER[n], band="NIR", outer=PANEL_POLYGONS[n])
```

:::{note}
**Panel marking GUI** (OpenCV windows): first drag a rough box and press ENTER; then, in the
zoomed view, left-click the corners. Right-click or Backspace removes the last point, `r`
restarts, ENTER finishes (min. 3 points), ESC cancels.
:::

## 5. Step 9: Empirical Line Method

```python
reflectance, elm_table, panel_table = compute_elm(capture, PANEL_POLYGONS_INNER, PANELS,
                                                  mode=ELM_MODE, max_saturation=MAX_SATURATION_PERCENT)
display(elm_table)
display(panel_table)
show_elm(elm_table, panel_table)

ndvi = (reflectance["NIR"] - reflectance["R"]) / (reflectance["NIR"] + reflectance["R"])
show_reflectance(reflectance, ndvi)

# Plausibility check: each panel should return the reflectance entered in PANELS
# (exact for 1- and 2-point, only approximately for ≥3 panels)
for name, poly in PANEL_POLYGONS_INNER.items():
    m = polygon_mask(poly, reflectance["G"].shape)
    for band in BANDS:
        print(f"{name:8s} {band:3s}: measured {np.nanmean(reflectance[band][m]):.4f}  "
              f"(expected {PANELS[name][band]})")
```

### Export in image space

```python
import tifffile

os.makedirs(OUTPUT_DIR, exist_ok=True)
capture_name = os.path.basename(capture["files"]["G"]).rsplit("_MS_", 1)[0]
rasters = {**{band: reflectance[band] for band in BANDS}, "NDVI": ndvi}

for name, data in rasters.items():
    path = os.path.join(OUTPUT_DIR, f"{capture_name}_{name}_imagespace.tif")
    tifffile.imwrite(path, data.astype("float32"), photometric="minisblack", compression="zlib")
```

## 6. Step 10 (optional): georeferencing with GCPs

```python
if USE_GCPS:
    gcps = load_gcps(GCP_CSV)
    GCP_PIXELS = mark_gcps(capture, gcps)          # click each target centre
    georef = fit_georeference(GCP_PIXELS, gcps, kind=GEOREF_TRANSFORM, check_points=CHECK_POINTS)
    display(georef["table"])
    show_georef_check(capture, gcps, GCP_PIXELS, georef, panel_polygons=PANEL_POLYGONS)

    geo, grid = georeference_rasters(rasters, georef, OUTPUT_RESOLUTION)
    show_georeferenced(geo, grid, gcps)

    write_geotiff(os.path.join(OUTPUT_DIR, f"{capture_name}_reflectance.tif"),
                  {b: geo[b] for b in BANDS}, grid)
    write_geotiff(os.path.join(OUTPUT_DIR, f"{capture_name}_NDVI.tif"), {"NDVI": geo["NDVI"]}, grid)
```

:::{tip}
`mark_gcps(capture, gcps, existing=GCP_PIXELS)` keeps already clicked points, so you can re-click
only a few. Press `c` in the rough-box window to skip a GCP.
:::

## Output files

| File | Content |
|---|---|
| `<capture>_<band>_imagespace.tif` | Reflectance per band (and NDVI) in image coordinates, float32, NaN = invalid |
| `<capture>_reflectance.tif` | 4-band GeoTIFF (G, R, RE, NIR), ETRS89 / UTM |
| `<capture>_NDVI.tif` | NDVI GeoTIFF, ETRS89 / UTM |

Without `rasterio`, one TIFF per band plus `.tfw` world file and `.prj` projection file is written
instead; QGIS and ArcGIS read these as well.
