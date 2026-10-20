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

```{mermaid}
flowchart TD
    raw["<b>0</b> One capture: 4 band TIFFs<br/>(G, R, RE, NIR) + EXIF/XMP metadata"]
    meta["pyexiftool: all 4 files in one call"] -.-> raw
    raw --> qual["<b>1</b> Quality filter<br/>RtkFlag = 50 and SurveyingMode = 1"]
    qual -- fail --> reject["reject capture"]
    qual -- pass --> sat

    subgraph perband ["per band"]
        sat["<b>2</b> Saturation mask from raw DN<br/>DN ≥ 65520 = 4095·16"]
        norm["<b>3</b> Black level + gain/exposure<br/>(DJI Eq. 9) → L in DN/s"]
        vig["<b>4</b> Vignetting correction<br/>(DJI Step 1, Eq. 7–8)"]
        dist["<b>5</b> Lens distortion<br/>(DJI Step 2, DewarpData)"]
        hom["<b>6</b> Factory homography<br/>(DJI Step 3, CalibratedHMatrix)"]
        ecc["<b>7</b> Fine alignment to R<br/>Gauss → Sobel → ECC"]
        sat --> norm --> vig --> dist --> hom --> ecc
    end

    ecc --> panel["<b>8</b> Mark panel(s), shrink 10 %<br/>→ mean L, saturation %, CV"]
    cert["Certified panel reflectance<br/>ρ per band"] --> elm
    panel --> elm["<b>9</b> Empirical Line Method<br/>1-point: ρ = F·L · 2-point: ρ = a·L + b"]
    elm --> refl["Surface reflectance (0–1) per band"]
    refl -.-> geo["<b>10</b> Optional: GCP georeferencing<br/>homography/affine, RMSE, leave-one-out"]
    gcp["GCP CSV (RTK rover)<br/>lon/lat ETRS89 → UTM"] --> geo
    geo --> final["GeoTIFF: reflectance (4 bands)<br/>ETRS89 / UTM 32N (EPSG:25832)"]

    classDef perb fill:#eaf6ea,stroke:#3b7a3b
    classDef cal fill:#fdf0e3,stroke:#c0702a
    classDef geo fill:#fbeaea,stroke:#a33
    class sat,norm,vig,dist,hom,ecc perb
    class panel,elm,cert cal
    class geo,gcp,final geo
```

## Why this order?

- The **quality filter** runs first, so no time is spent on captures that are discarded anyway.
- **Saturation** can only be detected unambiguously in the raw data, so the mask is built before
  any correction and then passed through the same geometry as the image.
- The **black level** is subtracted *before* vignetting (deviation from the DJI guide, see
  {ref}`blacklevel-order`).
- **Georeferencing** resamples the data and therefore happens only once, at the very end; panel
  extraction and ELM work on the original (aligned) image pixels.
