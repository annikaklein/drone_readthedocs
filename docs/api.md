# API Reference — `m3m_processing`

Complete reference of the module, generated automatically from the docstrings.
Click **[source]** next to any function to see its code.

## Structure of the module

| Section | Functions | Steps |
|---|---|---|
| Settings | `configure` | – |
| Loading | `find_bands`, `read_metadata`, `quality_ok` | 0, 1 |
| Radiometry | `radiometric_correction` | 3, 4 |
| Geometry | `geometric_correction`, `edge_image`, `ecc_align`, `apply_affine` | 5, 6, 7 |
| Putting it together | `load_capture` | 0–7 |
| Marking panels | `mark_panel`, `shrink_polygon`, `polygon_mask`, `show_polygon` | 8 |
| Reflectance | `panel_statistics`, `compute_elm`, `show_elm` | 8, 9 |
| Visualisation | `show_bands`, `show_reflectance`, `band_cmap` | – |
| Camera position | `camera_position`, `show_position_tags` | – |
| Georeferencing | `lonlat_to_utm`, `load_gcps`, `mark_gcps`, `fit_georeference`, `georeference_rasters`, `write_geotiff`, `show_georef_check`, `show_georeferenced` | 10 |

## Module settings

Changed with {func}`m3m_processing.configure`:

| Setting | Default | Meaning |
|---|---|---|
| `REFERENCE_BAND` | `"R"` | Band the others are aligned to via ECC |
| `QUALITY_FILTER` | `True` | `False` = also process images without RTK Fixed / SurveyingMode |
| `EXIFTOOL_PATH` | `None` | Path to exiftool if Jupyter cannot find it |
| `GCP_UTM_ZONE` | `None` | `None` = automatic from longitude |

Constants: `BANDS = ["G", "R", "RE", "NIR"]`, `SATURATION_DN = 65520`.

## The `capture` dictionary

{func}`~m3m_processing.load_capture` returns a dict that all later functions take as input:

| Key | Content |
|---|---|
| `"dn"` | `{band: array}` — corrected values in DN/s |
| `"valid"` | `{band: bool mask}` — inside the image and not saturated |
| `"saturated"` | `{band: bool mask}` — saturated pixels (incl. safety margin) |
| `"tags"` | `{band: metadata dict}` |
| `"ecc"` | `{band: (2×3 warp matrix, correlation)}` |
| `"files"` | `{band: file path}` |

## Functions

```{eval-rst}
.. automodule:: m3m_processing
   :members:
   :undoc-members:
   :member-order: bysource
   :exclude-members: BANDS, SATURATION_DN, REFERENCE_BAND, QUALITY_FILTER, EXIFTOOL_PATH, GCP_UTM_ZONE, BAND_COLOURS, SATURATION_COLOUR
```
