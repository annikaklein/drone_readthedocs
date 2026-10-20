# Quickstart

## Requirements

Python 3.12 with:

| Package | Purpose |
|---|---|
| `numpy`, `pandas`, `matplotlib` | arrays, tables, plots |
| `opencv-python` (tested with 4.10) | undistortion, warping, ECC, GUI for clicking |
| `pyexiftool` + the **ExifTool** program | reading the DJI XMP metadata |
| `rasterio` *(optional)* | multi-band GeoTIFF export |
| `pyproj` *(optional)* | camera position in UTM |
| `tifffile` | image-space TIFF export in the notebook |

```bash
conda install -c conda-forge numpy pandas matplotlib opencv exiftool rasterio pyproj tifffile
pip install pyexiftool
```

If Jupyter cannot find ExifTool, check `which exiftool` and pass the path via
`m3m.configure(EXIFTOOL_PATH="...")`.

## Minimal example

Put `m3m_processing.py` next to your notebook and the four band images of one capture.

```python
import m3m_processing as m3m
from m3m_processing import *

m3m.configure(REFERENCE_BAND="R", QUALITY_FILTER=True)

# Steps 0–7: load and correct (any one band file is enough)
capture = load_capture("DJI_20260820154930_0016_MS_G.TIF")

# Step 8: mark the panel (two OpenCV windows: rough box, then click corners)
PANELS = {"bright": {"G": 0.513, "R": 0.512, "RE": 0.511, "NIR": 0.509}}
poly = mark_panel(capture, band="NIR", name="bright")
inner = {"bright": shrink_polygon(poly, 0.10)}

# Step 9: Empirical Line Method
reflectance, elm_table, panel_table = compute_elm(capture, inner, PANELS, mode="1-point")
ndvi = (reflectance["NIR"] - reflectance["R"]) / (reflectance["NIR"] + reflectance["R"])
show_reflectance(reflectance, ndvi)
```

The result `reflectance[band]` is a float array with values 0–1; invalid pixels
(saturated or outside the image) are `NaN`.

For the full workflow including GCP georeferencing and GeoTIFF export see {doc}`notebook_usage`.
