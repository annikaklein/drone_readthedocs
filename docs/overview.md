# Processing Pipeline Overview

The pipeline processes **one capture at a time**, i.e. the four multispectral images
(`_MS_G`, `_MS_R`, `_MS_RE`, `_MS_NIR`) that the Mavic 3M records at a single trigger.
All four bands are read once, corrected identically, aligned to a common reference band (R),
and converted to surface reflectance using one or more reflectance panels visible in the same
capture. Georeferencing with ground control points is an optional final step.

## Order of operations at a glance

| # | Operation | Source | Function |
|---|---|---|---|
| 0 | Read capture + metadata | – | {func}`~m3m_processing.find_bands`, {func}`~m3m_processing.read_metadata` |
| 1 | Quality filter | DJI metadata table | {func}`~m3m_processing.quality_ok` |
| 2 | Saturation mask | sensor bit depth | {func}`~m3m_processing.load_capture` |
| 3 | Black level, gain, exposure | DJI Eq. 9 | {func}`~m3m_processing.radiometric_correction` |
| 4 | Vignetting | DJI Step 1, Eq. 7–8 | {func}`~m3m_processing.radiometric_correction` |
| 5 | Lens distortion | DJI Step 2 | {func}`~m3m_processing.geometric_correction` |
| 6 | Factory homography | DJI Step 3 | {func}`~m3m_processing.geometric_correction` |
| 7 | ECC fine alignment | DJI Step 4, Method 1 | {func}`~m3m_processing.edge_image`, {func}`~m3m_processing.ecc_align` |
| 8 | Panel extraction | – | {func}`~m3m_processing.mark_panel`, {func}`~m3m_processing.panel_statistics` |
| 9 | Empirical Line Method | Smith & Milton (1999) | {func}`~m3m_processing.compute_elm` |
| 10 | GCP georeferencing (optional) | Karney (2011) | {func}`~m3m_processing.fit_georeference`, {func}`~m3m_processing.write_geotiff` |

## Flow diagram

```{figure} figures/pipeline.svg
:alt: Processing pipeline flow diagram
:width: 100%
:align: center

Processing pipeline for one capture. Green: per-band corrections (Steps 2–7);
orange: panel calibration (Steps 8–9); red: optional georeferencing (Step 10).
```

## Why this order?

- The **quality filter** runs first, so no time is spent on captures that are discarded anyway.
- **Saturation** can only be detected unambiguously in the raw data, so the mask is built before
  any correction and then passed through the same geometry as the image.
- The **black level** is subtracted *before* vignetting (deviation from the DJI guide, see
  {ref}`blacklevel-order`).
- **Georeferencing** resamples the data and therefore happens only once, at the very end; panel
  extraction and ELM work on the original (aligned) image pixels.
