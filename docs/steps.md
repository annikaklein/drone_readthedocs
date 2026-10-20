# Step-by-Step Processing

Each step is described with **what** is computed, the **source** of the formula, and **why**
it is done. Short code excerpts show the corresponding lines of `m3m_processing.py`.
Equation and step numbers labelled "DJI" refer to the *Mavic 3M Image Processing Guide* v1.0
(DJI, 2023). Symbols are listed in {doc}`notation`.

---

## Step 0 — Reading one capture

**What.** From any one band image the file names of the other three bands of the same trigger
are derived (`…_MS_G/R/RE/NIR.TIF`). The metadata of all four files are read in a single
`exiftool` call.

**Why.** Each band comes from a separate camera with its own exposure, gain, vignetting,
distortion and homography parameters. All corrections therefore use the metadata of
*the band itself*.

Functions: {func}`~m3m_processing.find_bands`, {func}`~m3m_processing.read_metadata`

---

## Step 1 — Quality filter

**What.** A capture is processed only if

$$
\texttt{RtkFlag} = 50 \quad\wedge\quad \texttt{SurveyingMode} = 1 .
$$

**Source.** DJI Guide, metadata table (pp. 2–3): `RtkFlag` 50 = fixed RTK solution (cm-level);
`SurveyingMode` 1 = recommended, since the accuracy can be guaranteed.

**Why.** Done first, so that no processing time is spent on captures that would be discarded
anyway. Can be switched off with `configure(QUALITY_FILTER=False)`.

```python
rtk = int(t.get("XMP:RtkFlag", 0))
survey = int(t.get("XMP:SurveyingMode", 0))
return rtk == 50 and survey == 1, rtk, survey
```

---

## Step 2 — Saturation mask

**What.** The sensor digitises with 12 bit; the TIFF stores the values multiplied by 16
(16-bit container). The maximum possible value is therefore $4095 \cdot 16 = 65520$.
Every pixel with

$$
I \geq 65520
$$

is flagged as saturated. The mask is generated from the **raw** data and then passed through
exactly the same geometric operations as the image (Steps 5–7). After interpolation, any pixel
touched by a saturated pixel is flagged (conservative safety margin).

**Why.** A saturated pixel only states "at least this bright"; its true value is unknown.
Saturated pixels are excluded from the panel statistics and set to `NaN` in the reflectance
product. Only in the raw data is saturation unambiguous.

```python
SATURATION_DN = 65520                      # 4095 x 16
sat = (raw >= SATURATION_DN).astype("float32")
sat = geometric_correction(sat, t) > 0     # any contact = saturated
```

---

## Step 3 — Black level and gain/exposure normalisation

**What.**

$$
L_i = \frac{I_i - BL_i}{g_i \cdot t_{\text{exp},i}/10^{6}} \qquad [\text{DN s}^{-1}]
$$ (eq-norm)

with $BL$ = `BlackLevel`, $g$ = `SensorGain`, $t_\text{exp}$ = `ExposureTime` (XMP drone-dji).
Negative values (noise below the black level) are set to 0.

**Source.** DJI Eq. 9 (p. 10). DJI additionally divides $I$ and $BL$ by
$2^{\text{bitnum}} = 2^{16} = 65536$; this constant factor is omitted because it cancels in the
Empirical Line Method and in all normalised indices.

**Why.** The black level is an electronic offset present even without light. Gain and exposure
differ between bands and captures; normalising to DN s⁻¹ makes the signals proportional to the
incident radiance and comparable.

```python
dn = (img - t["XMP:BlackLevel"]) / (t["XMP:SensorGain"] * t["XMP:ExposureTime"] / 1e6)
dn = dn.clip(min=0)
```

---

## Step 4 — Vignetting correction

**What.**

$$
\begin{aligned}
r(x,y) &= \sqrt{(x - C_X)^2 + (y - C_Y)^2} \\
V(x,y) &= k_5 r^6 + k_4 r^5 + k_3 r^4 + k_2 r^3 + k_1 r^2 + k_0 r + 1 \\
L_i &\leftarrow L_i \cdot V(x,y)
\end{aligned}
$$ (eq-vig)

with $C_X, C_Y$ = `CalibratedOpticalCenterX/Y` and $k_0 \ldots k_5$ = `VignettingData`.

**Source.** DJI Step 1, Eq. 7–8 (p. 8).

**Why.** The lens transmits less light towards the image edges. $V$ compensates this radially
from the optical centre ($V = 1$ at the centre).

```python
cx, cy = t["XMP:CalibratedOpticalCenterX"], t["XMP:CalibratedOpticalCenterY"]
k = [float(v.strip()) for v in str(t["XMP:VignettingData"]).split(",")]
yy, xx = np.indices((h, w))
r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
factor = k[5]*r**6 + k[4]*r**5 + k[3]*r**4 + k[2]*r**3 + k[1]*r**2 + k[0]*r + 1.0
dn = dn * factor
```

(blacklevel-order)=
### Deviation from the guide: black level before vignetting

The guide applies Eq. 7 to the input image $I$ and introduces Eq. 9 only afterwards. Here the
black level is subtracted **before** vignetting correction, because the black level is an
electronic offset that does not pass through the optics. Applying $V$ to the raw value would
amplify the offset as well:

$$
\underbrace{I\,V - BL}_{\text{guide, literal}} - \underbrace{(I-BL)\,V}_{\text{implemented}} = BL\,(V-1).
$$

:::{admonition} Example
:class: note

$I = 5000$, $BL = 3200$, $V = 2$:
implemented $(5000-3200)\cdot 2 = 3600$ (correct);
literal $5000\cdot 2 - 3200 = 6800$, i.e. 3200 too high.
:::

The error is zero at the image centre ($V = 1$) and grows towards the edges; with the example
coefficients in the guide, $V \approx 3.6$ in the image corner. A numerical test with the example
parameters of the guide confirmed that the implemented order reproduces a known input signal
exactly, whereas the literal order overestimated it by up to 65 % at the corners (mean 12 %).

All other operations (Eq. {eq}`eq-norm` and Steps 5–7) are linear with respect to a constant
offset and a constant factor, so their order relative to each other does not affect the result.
Only the vignetting factor varies from pixel to pixel.

---

## Step 5 — Lens distortion correction

**What.** Camera matrix and distortion coefficients from `DewarpData`
($f_x, f_y, c_x, c_y, k_1, k_2, p_1, p_2, k_3$):

$$
K = \begin{pmatrix} f_x & 0 & C_X + c_x \\ 0 & f_y & C_Y + c_y \\ 0 & 0 & 1 \end{pmatrix},
\qquad \mathbf{d} = (k_1, k_2, p_1, p_2, k_3).
$$

The image is resampled with OpenCV `initUndistortRectifyMap` + `remap` (bilinear), using $K$
also as the new camera matrix.

**Source.** DJI Step 2 (p. 9). `cv2.undistort()` internally performs exactly these two calls; the
guide explicitly requires that the camera matrix is *not* changed (`newCameraMatrix` $= K$). The
two-call form is used so that the masks can be transformed with exactly the same mapping.

**Why.** Radial and tangential lens distortion would otherwise prevent pixel-accurate band
alignment and georeferencing.

```python
camera_matrix = np.array([[fx, 0, center_x + cx],
                          [0, fy, center_y + cy],
                          [0, 0, 1]])
distortion = np.array([k1, k2, p1, p2, k3])
map1, map2 = cv2.initUndistortRectifyMap(camera_matrix, distortion, None,
                                         camera_matrix, (w, h), cv2.CV_32FC1)
undistorted = cv2.remap(img, map1, map2, cv2.INTER_LINEAR)
```

---

## Step 6 — Band alignment with the factory homography

**What.**

$$
\begin{pmatrix} x' \\ y' \\ w' \end{pmatrix} = \mathbf{H}_i \begin{pmatrix} x \\ y \\ 1 \end{pmatrix},
\qquad (x_\text{new}, y_\text{new}) = (x'/w',\; y'/w')
$$

with $\mathbf{H}_i$ = `CalibratedHMatrix` (3×3), applied with `cv2.warpPerspective`.

**Source.** DJI Step 3 (p. 9): projective transformation from the individual physical image
plane to the designed ideal image plane.

**Why.** The four cameras are mounted side by side; $\mathbf{H}_i$ corrects position and rotation
differences. According to DJI this is sufficient in hover mode only.

```python
h_matrix = np.array([float(v) for v in str(t["XMP:CalibratedHMatrix"]).split(",")]).reshape(3, 3)
aligned = cv2.warpPerspective(undistorted, h_matrix, (w, h), flags=cv2.INTER_LINEAR)
```

---

## Step 7 — Fine alignment (ECC)

**What.** For every band except the reference band (R):

1. scale robustly to 0–1 (1st–99th percentile), Gaussian smoothing (5×5);
2. Sobel edge magnitude $E = \sqrt{G_x^2 + G_y^2}$ (3×3 kernel);
3. find the affine warp $\mathbf{W}$ that maximises the enhanced correlation coefficient between
   the edge images of reference and band (`cv2.findTransformECC`, `MOTION_AFFINE`,
   ≤ 300 iterations, $\varepsilon = 10^{-7}$, valid pixels only);
4. apply $\mathbf{W}$ to the band and to its masks.

**Source.** DJI Step 4, Method 1 (p. 9); ECC algorithm: Evangelidis & Psarakis (2008).

**Why.** In flight the platform moves between the slightly different exposure times of the
cameras, leaving a residual offset of a few pixels after Step 6 (observed: 3–6 px). Edge images
are used instead of intensities because the bands differ strongly in brightness (vegetation dark
in R, bright in NIR), while edges are at the same positions. Correlation coefficient and shift are
reported per band as a quality measure; lower correlations for RE and NIR are expected for
spectral reasons and should be checked visually.

```python
b = cv2.GaussianBlur(b, (5, 5), 0)
gx = cv2.Sobel(b, cv2.CV_32F, 1, 0, ksize=3)
gy = cv2.Sobel(b, cv2.CV_32F, 0, 1, ksize=3)
edges = cv2.magnitude(gx, gy)
cc, warp = cv2.findTransformECC(edges_ref, edges_band, warp, cv2.MOTION_AFFINE,
                                criteria, ref_mask, 5)
```

:::{tip}
If ECC does not converge, the band is kept without fine alignment and a warning is printed.
Check the shift values: anything far above the observed 3–6 px is suspicious.
:::

---

## Step 8 — Panel extraction

**What.** Each reflectance panel is marked as a polygon (corner points clicked in a zoomed view;
works for rotated panels). The polygon is shrunk by 10 % per side towards its centroid,

$$
\mathbf{p}_k' = \bar{\mathbf{p}} + (1 - 2\cdot 0.1)\,(\mathbf{p}_k - \bar{\mathbf{p}}),
$$

to exclude edge and mixed pixels. For every band the mean $\overline{L}_{\text{panel},i}$ of all
valid (non-saturated, inside-image) pixels, the saturated fraction and the coefficient of
variation are computed. Since all bands are aligned (Step 7), one polygon serves all bands.

**Why.** The panel provides a target of known reflectance under exactly the illumination of the
capture. A low coefficient of variation (< 2 %) shows that no shadow or edge pixels are included.

Functions: {func}`~m3m_processing.mark_panel`, {func}`~m3m_processing.shrink_polygon`,
{func}`~m3m_processing.panel_statistics`

---

## Step 9 — Empirical Line Method (ELM)

### 1-point (one panel, line through the origin)

$$
F_i = \frac{\rho_{\text{panel},i}}{\overline{L}_{\text{panel},i}}, \qquad
\rho_i(x,y) = F_i \, L_i(x,y).
$$ (eq-elm1)

### 2-point / multi-point (two or more panels, line with offset)

$$
\rho_i(x,y) = a_i \, L_i(x,y) + b_i, \qquad
(a_i, b_i) = \arg\min \sum_{p} \big(\rho_{p,i} - a_i \overline{L}_{p,i} - b_i\big)^2
$$ (eq-elm2)

with $R^2$ reported for three or more panels. The method is selected with
`ELM_MODE = "1-point"` or `"2-point"`.

**Source.** Empirical Line Method: Smith & Milton (1999); certified panel reflectance
$\rho_{\text{panel},i}$ from the panel's calibration certificate at the band centre wavelengths.

**Assumptions.** The 1-point version assumes zero offset ($b = 0$), which is justified because
the black level has already been removed and path radiance is negligible at low flight altitude.
The 2-point version removes any remaining offset (stray light, residual dark signal) and is
preferred when a dark and a bright panel are available.

**Saturation handling.** A panel with more than 1 % saturated pixels in a band is not used for
that band; if only one panel remains, that band falls back to the 1-point method and a warning
is printed.

```python
if len(usable) == 1:                       # 1-point
    a, b = rho[0] / L[0], 0.0
else:                                      # 2-/multi-point
    a, b = np.polyfit(L, rho, 1)
reflectance = a * capture["dn"][band] + b
reflectance[~capture["valid"][band]] = np.nan
```

### Why not the sunlight sensor?

DJI's own method (Eq. 2–6) relates the camera signal to the sunlight sensor (`Irradiance`,
`SensorGainAdjustment`). Because a panel is visible in the same capture, it records the actual
illumination at ground level directly, which is more accurate than the sensor on top of the
aircraft (affected by attitude and sun angle). The panel-derived $F_i$ (or $a_i, b_i$) implicitly
contains all camera-specific gain factors, so `SensorGainAdjustment` is not needed.

The sunlight sensor becomes relevant only to transfer a panel calibration to captures *without*
a panel:

$$
\rho_i^{(j)} = F_i^{(\text{panel})}\,L_i^{(j)}\;\frac{E_i^{(\text{panel})}}{E_i^{(j)}},
$$

with $E$ the `Irradiance` value of the same band (not implemented in the current single-capture
workflow).

---

## Step 10 — Optional: georeferencing with GCPs

**What.**

1. Read the rover CSV (e.g. Emlid Flow). If `Easting/Northing` are empty, `Longitude/Latitude`
   (ETRS89) are converted to ETRS89/UTM (zone from longitude; here 32N, EPSG:25832) with the
   Krüger series (Karney, 2011; deviation from PROJ < 1 µm).
2. Click each GCP target centre in the reference band.
3. Fit pixel → UTM by least squares: homography (≥ 4 points, also corrects a slight oblique view)
   or affine (≥ 3 points).
4. Report residuals, RMSE of control points, leave-one-out RMSE and the error at independent
   check points.
5. Resample reflectance once onto a north-up grid (pixel size ≈ GSD) and write a GeoTIFF
   (`rasterio`; fallback: TIFF + `.tfw` + `.prj`).

**Why last?** Panel extraction and ELM work on original image pixels; georeferencing resamples the
data, which should happen only once and at the end. The single-image homography assumes flat
terrain.

:::{warning}
With exactly 4 control points a homography fits perfectly — the control-point RMSE is then 0 and
not meaningful. Use the leave-one-out RMSE or, better, independent check points (`CHECK_POINTS`).
:::

Functions: {func}`~m3m_processing.load_gcps`, {func}`~m3m_processing.mark_gcps`,
{func}`~m3m_processing.fit_georeference`, {func}`~m3m_processing.georeference_rasters`,
{func}`~m3m_processing.write_geotiff`
