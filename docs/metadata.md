# Metadata Fields Used

All fields are read from the `XMP:drone-dji` block of each band image with `pyexiftool`.

| Field | Step | Use |
|---|---|---|
| `RtkFlag`, `SurveyingMode` | 1 | Quality filter (keep 50 / 1). |
| `BlackLevel` | 3 | Offset subtracted before all other corrections. |
| `SensorGain`, `ExposureTime` | 3 | Normalisation to DN s⁻¹ (Eq. {eq}`eq-norm`). |
| `CalibratedOpticalCenterX/Y` | 4, 5 | Vignetting centre; principal point of $K$. |
| `VignettingData` | 4 | $k_0 \ldots k_5$ (Eq. {eq}`eq-vig`). |
| `DewarpData` | 5 | $f_x, f_y, c_x, c_y, k_1, k_2, p_1, p_2, k_3$. |
| `CalibratedHMatrix` | 6 | Per-band 3×3 homography. |
| `BandName`, `BandFreq` | – | Band identification; centre wavelength and HWHM. |
| `GpsLatitude/Longitude`, `RelativeAltitude` | – | Camera position; GSD estimate $\text{GSD} = h/f_x$. |
| `Irradiance`, `SensorGainAdjustment` | – | Not used (panel-based calibration). |

:::{tip}
`show_position_tags(capture)` lists every position/attitude-related tag of a capture — useful
when a field name differs between firmware versions.
:::
