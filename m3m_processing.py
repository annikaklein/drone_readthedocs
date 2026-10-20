"""
m3m_processing.py
=================
Processing functions for DJI Mavic 3M multispectral captures:
loading, quality filter, radiometric/geometric correction (DJI Image Processing
Guide, Steps 1-4), panel marking, Empirical Line Method, camera position and
optional GCP georeferencing / GeoTIFF export.

Usage in a notebook (file in the same folder)::

    import m3m_processing as m3m
    m3m.configure(REFERENCE_BAND="R", QUALITY_FILTER=True)
    capture = m3m.load_capture("DJI_..._MS_G.TIF")
"""
import glob, os, re
import numpy as np
import pandas as pd
import cv2
import exiftool
import matplotlib.pyplot as plt

# ---------- Settings (change with configure(...)) -------------------------

REFERENCE_BAND = "R"      # band the others are aligned to via ECC
QUALITY_FILTER = True     # False = also process images without RTK Fixed / SurveyingMode
EXIFTOOL_PATH = None      # path to exiftool if Jupyter cannot find it, otherwise None
GCP_UTM_ZONE = None       # None = automatic from longitude


def configure(**settings):
    """Changes module settings, e.g. configure(REFERENCE_BAND="G", EXIFTOOL_PATH="/opt/anaconda3/bin/exiftool")."""
    allowed = {"REFERENCE_BAND", "QUALITY_FILTER", "EXIFTOOL_PATH", "GCP_UTM_ZONE"}
    for key, value in settings.items():
        if key not in allowed:
            raise KeyError(f"Unknown setting '{key}'. Allowed: {sorted(allowed)}")
        globals()[key] = value
    print("m3m_processing settings:", {k: globals()[k] for k in sorted(allowed)})


# Hide OpenCV warnings (accessible differently depending on the OpenCV version)
try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except AttributeError:
    try:
        cv2.setLogLevel(2)   # 2 = errors only
    except AttributeError:
        pass

BANDS = ["G", "R", "RE", "NIR"]
SATURATION_DN = 65520        # 4095 × 16 → 12-bit maximum, saturated

# ---------- Colour scales per band -----------------------------------------
from matplotlib.colors import LinearSegmentedColormap

BAND_COLOURS = {"G": "#2ca02c", "R": "#d62728", "RE": "#ff7f0e", "NIR": "#8c2d9c"}
SATURATION_COLOUR = (0, 1, 1)   # cyan – visible on all band colour scales


def band_cmap(band):
    """Colour scale for one band: black (low) → band colour → white (high)."""
    return LinearSegmentedColormap.from_list(f"{band}_scale", ["black", BAND_COLOURS[band], "white"])


# ---------- Loading --------------------------------------------------------

def find_bands(path):
    """Finds the files of all 4 bands belonging to the same capture as the given MS image."""
    m = re.match(r"(.*)_MS_(G|R|RE|NIR)\.TIF$", path, flags=re.IGNORECASE)
    if not m:
        raise ValueError(f"Not an MS file name: {path}")
    base = m.group(1)
    files = {}
    for band in BANDS:
        hits = glob.glob(f"{base}_MS_{band}.TIF") + glob.glob(f"{base}_MS_{band}.tif")
        if not hits:
            raise FileNotFoundError(f"Band {band} missing: {base}_MS_{band}.TIF")
        files[band] = hits[0]
    return files


def read_metadata(files):
    """Reads the metadata of all bands in ONE exiftool call."""
    kwargs = {"executable": EXIFTOOL_PATH} if EXIFTOOL_PATH else {}
    with exiftool.ExifToolHelper(**kwargs) as et:
        meta = et.get_metadata([files[b] for b in BANDS])
    return dict(zip(BANDS, meta))


def quality_ok(t):
    """True if RTK Fixed (RtkFlag 50) AND flagged as survey-grade by DJI (SurveyingMode 1)."""
    rtk = int(t.get("XMP:RtkFlag", 0))
    survey = int(t.get("XMP:SurveyingMode", 0))
    return rtk == 50 and survey == 1, rtk, survey


# ---------- Radiometry -----------------------------------------------------

def radiometric_correction(raw, t):
    """Subtract black level, normalise by gain × exposure (s), correct vignetting → DN/s."""
    img = raw.astype("float64")
    dn = (img - t["XMP:BlackLevel"]) / (t["XMP:SensorGain"] * t["XMP:ExposureTime"] / 1e6)
    dn = dn.clip(min=0)

    cx, cy = t["XMP:CalibratedOpticalCenterX"], t["XMP:CalibratedOpticalCenterY"]
    k = [float(v.strip()) for v in str(t["XMP:VignettingData"]).split(",")]
    h, w = dn.shape
    yy, xx = np.indices((h, w))
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    factor = k[5]*r**6 + k[4]*r**5 + k[3]*r**4 + k[2]*r**3 + k[1]*r**2 + k[0]*r + 1.0
    return dn * factor


# ---------- Geometry -------------------------------------------------------

def geometric_correction(img, t, interpolation=cv2.INTER_LINEAR):
    """Undistortion (DewarpData) + alignment (CalibratedHMatrix)."""
    numbers = str(t["XMP:DewarpData"]).split(";")[-1]
    fx, fy, cx, cy, k1, k2, p1, p2, k3 = [float(v) for v in numbers.split(",")]
    center_x, center_y = t["XMP:CalibratedOpticalCenterX"], t["XMP:CalibratedOpticalCenterY"]

    camera_matrix = np.array([[fx, 0, center_x + cx],
                              [0, fy, center_y + cy],
                              [0, 0, 1]], dtype="float64")
    distortion = np.array([k1, k2, p1, p2, k3])

    h, w = img.shape[:2]
    map1, map2 = cv2.initUndistortRectifyMap(camera_matrix, distortion, None,
                                             camera_matrix, (w, h), cv2.CV_32FC1)
    undistorted = cv2.remap(img, map1, map2, interpolation)

    h_matrix = np.array([float(v) for v in str(t["XMP:CalibratedHMatrix"]).split(",")]).reshape(3, 3)
    return cv2.warpPerspective(undistorted, h_matrix, (w, h), flags=interpolation)


def edge_image(dn, mask):
    """Smoothing + Sobel edge magnitude, scaled to 0–1 (robust via percentiles)."""
    lo, hi = np.percentile(dn[mask], [1, 99])
    b = np.clip((dn - lo) / (hi - lo + 1e-12), 0, 1).astype("float32")
    b = cv2.GaussianBlur(b, (5, 5), 0)
    gx = cv2.Sobel(b, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(b, cv2.CV_32F, 0, 1, ksize=3)
    k = cv2.magnitude(gx, gy)
    return k / (k.max() + 1e-12)


def ecc_align(ref_dn, ref_mask, dn, mask):
    """Finds the affine residual correction that maps dn onto ref_dn. Returns matrix and correlation."""
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-7)
    try:
        cc, warp = cv2.findTransformECC(edge_image(ref_dn, ref_mask), edge_image(dn, mask), warp,
                                        cv2.MOTION_AFFINE, criteria,
                                        ref_mask.astype(np.uint8), 5)
    except cv2.error:
        print("   ⚠ ECC did not converge – band stays without fine alignment")
        cc = float("nan")
    return warp, cc


def apply_affine(img, warp, interpolation=cv2.INTER_LINEAR):
    h, w = img.shape[:2]
    return cv2.warpAffine(img, warp, (w, h), flags=interpolation + cv2.WARP_INVERSE_MAP)


# ---------- Putting it all together ----------------------------------------

def load_capture(path):
    """Loads all 4 bands of a capture once and corrects them completely.

    Returns a dict with::

      "dn"        → {"G": array, "R": ..., "RE": ..., "NIR": ...}   corrected values in DN/s
      "valid"     → {band: bool mask}   inside the image and not saturated
      "saturated" → {band: bool mask}   saturated pixels (incl. safety margin)
      "tags"      → {band: metadata}
      "ecc"       → {band: (matrix, correlation)}
      "files"     → {band: file path}

    or None if the quality filter rejects the capture.
    """
    files = find_bands(path)
    tags = read_metadata(files)
    print("Capture:", os.path.basename(files["G"]).replace("_MS_G.TIF", ""))

    # 1) Quality filter first – saves time on unusable images
    ok, rtk, survey = quality_ok(tags[REFERENCE_BAND])
    print(f"   Quality: RtkFlag={rtk} (50 = Fixed), SurveyingMode={survey} → {'OK' if ok else 'NOT OK'}")
    if QUALITY_FILTER and not ok:
        print("   → skipped")
        return None

    dn, valid, saturated, inside = {}, {}, {}, {}
    for band in BANDS:
        t = tags[band]
        raw = cv2.imread(files[band], cv2.IMREAD_UNCHANGED)
        if raw is None:
            raise FileNotFoundError(files[band])

        # 2) Saturation mask from the RAW values
        sat = (raw >= SATURATION_DN).astype("float32")
        ins = np.ones(raw.shape, dtype="float32")

        # 3) Radiometry, 4) geometry – masks go through the same geometry
        d = radiometric_correction(raw, t)
        d = geometric_correction(d, t)
        sat = geometric_correction(sat, t) > 0            # conservative: any contact = saturated
        ins = geometric_correction(ins, t, cv2.INTER_NEAREST) > 0.5

        dn[band], saturated[band], inside[band] = d, sat, ins
        valid[band] = ins & ~sat
        print(f"   {band:3s}: saturated raw {100 * (raw >= SATURATION_DN).mean():.3f} %"
              f"  | with safety margin {100 * sat.mean():.3f} %")

    # 5) ECC fine alignment of all other bands to the reference band
    ecc = {REFERENCE_BAND: (np.eye(2, 3, dtype=np.float32), 1.0)}
    for band in BANDS:
        if band == REFERENCE_BAND:
            continue
        warp, cc = ecc_align(dn[REFERENCE_BAND], valid[REFERENCE_BAND], dn[band], valid[band])
        ecc[band] = (warp, cc)
        dn[band] = apply_affine(dn[band].astype("float32"), warp).astype("float64")
        saturated[band] = apply_affine(saturated[band].astype("float32"), warp) > 0
        inside[band] = apply_affine(inside[band].astype("float32"), warp, cv2.INTER_NEAREST) > 0.5
        valid[band] = inside[band] & ~saturated[band]
        print(f"   ECC {band:3s} → {REFERENCE_BAND}: correlation {cc:.3f}, "
              f"shift x={warp[0, 2]:+.2f} px, y={warp[1, 2]:+.2f} px")

    return {"dn": dn, "valid": valid, "saturated": saturated, "tags": tags,
            "ecc": ecc, "files": files}


# ---------- Marking panels (GUI) -------------------------------------------

def _display_8bit(b, mask):
    lo, hi = np.percentile(b[mask], [1, 99.5])
    return (np.clip((b - lo) / (hi - lo + 1e-12), 0, 1) * 255).astype(np.uint8)


def _select_roi(window, img):
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    roi = cv2.selectROI(window, img, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(window)
    for _ in range(10):        # macOS: make sure the window closes
        cv2.waitKey(1)
    return roi


def _click_polygon(window, img):
    """Set corner points by mouse click. Left click = point, right click/Backspace = remove last,
    r = restart, ENTER = done (min. 3 points), ESC = cancel. Returns list of (x, y) in window image."""
    points = []

    def mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()

    colour = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, mouse)
    while True:
        view = colour.copy()
        if len(points) >= 2:
            cv2.polylines(view, [np.array(points, np.int32)], isClosed=len(points) >= 3,
                          color=(0, 0, 255), thickness=2)
        for p in points:
            cv2.circle(view, p, 5, (0, 255, 255), -1)
        cv2.putText(view, f"Points: {len(points)}  |  click=point  right click=undo  "
                          f"r=restart  ENTER=done  ESC=cancel",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.imshow(window, view)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10) and len(points) >= 3:      # ENTER
            break
        if key in (8, 127) and points:                # Backspace
            points.pop()
        if key == ord("r"):
            points.clear()
        if key == 27:                                  # ESC
            points = []
            break
    cv2.destroyWindow(window)
    for _ in range(10):        # macOS: make sure the window closes
        cv2.waitKey(1)
    return points


def mark_panel(capture, band="NIR", max_width=1400, zoom_width=900, name="Panel"):
    """Two steps: 1) roughly drag a box around the panel,
    2) in the zoomed view click the corners of the panel surface (any number, also rotated).
    Returns: polygon as array [[x, y], ...] in pixels of the aligned image."""
    b = capture["dn"][band]
    view = _display_8bit(b, capture["valid"][band])
    h, w = view.shape

    # Step 1: overview (downscaled) – drag a rough box
    s = min(1.0, max_width / w)
    small = cv2.resize(view, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    short = name.encode("ascii", "ignore").decode() or "Panel"
    x, y, bw, bh = _select_roi(f"1) {short}: rough box - ENTER", small)
    if bw == 0 or bh == 0:
        raise RuntimeError("Nothing selected.")
    x0, y0 = int(x / s), int(y / s)
    x1, y1 = min(w, int((x + bw) / s) + 1), min(h, int((y + bh) / s) + 1)

    # Step 2: zoom – click the corners
    crop = view[y0:y1, x0:x1]
    z = zoom_width / crop.shape[1]
    large = cv2.resize(crop, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
    points = _click_polygon(f"2) {short}: click corners", large)
    if len(points) < 3:
        raise RuntimeError("Cancelled or fewer than 3 points.")

    # Click position (centre of the enlarged pixel) → original pixel
    polygon = np.array([(x0 + px / z - 0.5, y0 + py / z - 0.5) for px, py in points])
    print(f"{name} polygon (x, y):", np.round(polygon, 1).tolist())
    return polygon


def shrink_polygon(polygon, fraction):
    """Shrinks the polygon towards its centroid (by 'fraction' per side), also for rotated panels."""
    polygon = np.asarray(polygon, dtype=float)
    centre = polygon.mean(axis=0)
    return centre + (polygon - centre) * (1 - 2 * fraction)


def polygon_mask(polygon, shape):
    """Bool mask: True for all pixels whose centre lies inside the polygon."""
    mask = np.zeros(shape, dtype=np.uint8)
    # Sub-pixel filling (shift=4 → 1/16 pixel)
    pts = np.round((np.asarray(polygon) + 0.5) * 16).astype(np.int32)
    cv2.fillPoly(mask, [pts], 1, lineType=cv2.LINE_8, shift=4)
    return mask.astype(bool)


def show_polygon(capture, polygon, band="NIR", margin=60, outer=None):
    b = capture["dn"][band]
    view = _display_8bit(b, capture["valid"][band])
    polygon = np.asarray(polygon)
    mask = polygon_mask(polygon, view.shape)
    xmin, ymin = np.floor(polygon.min(axis=0)).astype(int)
    xmax, ymax = np.ceil(polygon.max(axis=0)).astype(int)
    x0, y0 = max(0, xmin - margin), max(0, ymin - margin)
    x1, y1 = xmax + margin, ymax + margin

    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    ax[0].imshow(view, cmap="gray")
    ax[0].add_patch(plt.Polygon(polygon, fill=False, color="red", lw=1.5))
    ax[0].set_title(f"{band} – overview")
    ax[0].set_xlabel("x [px]"); ax[0].set_ylabel("y [px]")

    crop = cv2.cvtColor(view[y0:y1, x0:x1], cv2.COLOR_GRAY2RGB)
    m = mask[y0:y1, x0:x1]
    crop[m] = (0.6 * crop[m] + 0.4 * np.array([255, 0, 0])).astype(np.uint8)
    ax[1].imshow(crop, interpolation="nearest")
    if outer is not None:
        ax[1].add_patch(plt.Polygon(np.asarray(outer) - [x0, y0], fill=False, color="yellow", lw=1, ls="--"))
    ax[1].add_patch(plt.Polygon(polygon - [x0, y0], fill=False, color="red", lw=1.5))
    ax[1].set_title(f"Zoom: red = pixels used ({mask.sum()})" + ("; yellow = marked" if outer is not None else ""))
    ax[1].axis("off")
    plt.show()


# ---------- Reflectance: Empirical Line Method (1-point or 2-/multi-point) --

def panel_statistics(capture, polygons):
    """Mean, saturation and homogeneity of each panel in each band."""
    shape = capture["dn"][BANDS[0]].shape
    stat = {}
    for name, poly in polygons.items():
        panel = polygon_mask(poly, shape)
        if panel.sum() == 0:
            raise ValueError(f"Panel '{name}': polygon contains no pixels.")
        for band in BANDS:
            values = capture["dn"][band][panel & capture["valid"][band]]
            stat[(name, band)] = {
                "avg(L) [DN/s]": values.mean() if values.size else np.nan,
                "Pixels": int(values.size),
                "saturated [%]": 100 * capture["saturated"][band][panel].mean(),
                "Coeff. of variation [%]": 100 * values.std() / values.mean() if values.size else np.nan,
            }
    return stat


def compute_elm(capture, polygons, panels, mode="1-point", max_saturation=1.0):
    """Converts every band to reflectance with the Empirical Line Method.

    mode="1-point": reflectance = F · L with F = rho / avg(L) (line through the origin, first panel only)
    mode="2-point": reflectance = a · L + b, line through all panels (with ≥3 panels regression + R²)
    Panels with more than 'max_saturation' % saturated pixels are not used in that band;
    if only 1 panel is left, that band falls back to 1-point.
    """
    names = list(polygons)
    if mode == "1-point":
        names = names[:1]
    stat = panel_statistics(capture, {n: polygons[n] for n in names})

    reflectance, rows = {}, []
    for band in BANDS:
        usable = [n for n in names
                  if stat[(n, band)]["Pixels"] > 0 and stat[(n, band)]["saturated [%]"] <= max_saturation]
        rejected = [n for n in names if n not in usable]
        if rejected:
            print(f"⚠ {band}: panel {rejected} saturated/invalid → not used")
        if not usable:
            print(f"⚠ {band}: no usable panel – using '{names[0]}' anyway (result uncertain!)")
            usable = names[:1]

        L = np.array([stat[(n, band)]["avg(L) [DN/s]"] for n in usable])
        rho = np.array([panels[n][band] for n in usable])

        if len(usable) == 1:
            a, b, r2, method = rho[0] / L[0], 0.0, np.nan, "1-point"
        else:
            a, b = np.polyfit(L, rho, 1)
            predicted = a * L + b
            r2 = (1 - np.sum((rho - predicted) ** 2) / np.sum((rho - rho.mean()) ** 2)
                  if len(usable) >= 3 else np.nan)
            method = f"{len(usable)}-point"

        r = a * capture["dn"][band] + b
        r[~capture["valid"][band]] = np.nan
        reflectance[band] = r
        rows.append({"Band": band, "Method": method, "Panels": ", ".join(usable),
                     "Gain a": a, "Offset b": b, "R²": r2})

    tab_fit = pd.DataFrame(rows).set_index("Band")
    tab_panels = pd.DataFrame(
        [{"Panel": n, "Band": b, "rho": panels[n][b], **stat[(n, b)]} for n in names for b in BANDS]
    ).set_index(["Panel", "Band"])
    return reflectance, tab_fit, tab_panels


def show_elm(tab_fit, tab_panels):
    """Per band: panel measurements (points) and the fitted line."""
    fig, ax = plt.subplots(1, 4, figsize=(20, 4))
    for a, band in zip(ax, BANDS):
        pts = tab_panels.xs(band, level="Band")
        gain, off = tab_fit.loc[band, "Gain a"], tab_fit.loc[band, "Offset b"]
        x = np.linspace(0, np.nanmax(pts["avg(L) [DN/s]"]) * 1.15, 50)
        a.plot(x, gain * x + off, color="tab:blue", label=f"{tab_fit.loc[band, 'Method']}")
        for name, z in pts.iterrows():
            colour = "red" if z["saturated [%]"] > 0 else "black"
            a.scatter(z["avg(L) [DN/s]"], z["rho"], color=colour, zorder=3)
            a.annotate(name, (z["avg(L) [DN/s]"], z["rho"]), textcoords="offset points", xytext=(5, 5))
        a.axhline(0, color="0.7", lw=0.8); a.axvline(0, color="0.7", lw=0.8)
        a.set_title(band); a.set_xlabel("avg(L) [DN/s]"); a.set_ylabel("Reflectance")
        a.legend(fontsize=8)
    fig.suptitle("Empirical line: panels (red = partly saturated) and calibration line")
    plt.tight_layout()
    plt.show()


# ---------- Showing the bands ----------------------------------------------

def show_bands(capture, kind="corrected", marker_px=7):
    """Shows all 4 bands side by side (band colour scale) with saturated pixels marked cyan, and a histogram below each.
    kind="corrected" → values after all corrections (DN/s), saturation incl. safety margin
    kind="raw"       → unprocessed TIFF values (DN), saturation exactly = 65520"""
    fig, ax = plt.subplots(2, 4, figsize=(22, 9), gridspec_kw={"height_ratios": [3, 1.3]})
    for i, band in enumerate(BANDS):
        if kind == "raw":
            img = cv2.imread(capture["files"][band], cv2.IMREAD_UNCHANGED).astype("float64")
            sat = img >= SATURATION_DN
            unit = "DN (raw)"
        else:
            img = capture["dn"][band]
            sat = capture["saturated"][band]
            unit = "DN/s (corrected)"

        values = img[np.isfinite(img) & (img > 0)]
        vmin, vmax = np.percentile(values, [1, 99.5])

        # Greyscale image
        a = ax[0, i]
        im = a.imshow(img, cmap=band_cmap(band), vmin=vmin, vmax=vmax)
        plt.colorbar(im, ax=a, fraction=0.035, label=unit)

        # Saturated pixels in cyan – slightly enlarged for the overview, otherwise invisible
        visible = cv2.dilate(sat.astype(np.uint8), np.ones((marker_px, marker_px), np.uint8))
        overlay = np.zeros((*sat.shape, 4))
        overlay[visible > 0] = [*SATURATION_COLOUR, 0.9]
        a.imshow(overlay, interpolation="nearest")
        a.set_title(f"{band}: {100 * sat.mean():.3f} % saturated ({sat.sum()} px)")
        a.set_xlabel("x [px]"); a.set_ylabel("y [px]")

        # Histogram
        h = ax[1, i]
        h.hist(values, bins=200, color=BAND_COLOURS[band])
        h.set_yscale("log")
        if kind == "raw":
            h.axvline(SATURATION_DN, color="black", lw=1.5, label="Saturation 65520")
            h.axvline(capture["tags"][band]["XMP:BlackLevel"], color="0.5", lw=1.5, ls="--",
                      label="Black level")
            h.legend(fontsize=8)
        h.set_xlabel(unit)
        h.set_ylabel("Number of pixels (log)")

    fig.suptitle("Raw values" if kind == "raw" else "Corrected values", fontsize=14)
    plt.tight_layout()
    plt.show()


# ---------- Camera position from the metadata ------------------------------

def _tag(t, *names):
    """Looks up a metadata entry under several possible names (with or without group)."""
    for n in names:
        if n in t:
            return t[n]
    short = {k.split(":")[-1].lower(): v for k, v in t.items()}
    for n in names:
        if n.split(":")[-1].lower() in short:
            return short[n.split(":")[-1].lower()]
    return None


def camera_position(capture, band=None):
    """Position and attitude of the camera at capture time + rough estimate of GSD and footprint."""
    band = band or REFERENCE_BAND
    t = capture["tags"][band]
    pos = {
        "Latitude [°]":             _tag(t, "XMP:GpsLatitude", "Composite:GPSLatitude"),
        "Longitude [°]":            _tag(t, "XMP:GpsLongitude", "XMP:GpsLongtitude", "Composite:GPSLongitude"),
        "Absolute altitude [m]":    _tag(t, "XMP:AbsoluteAltitude", "Composite:GPSAltitude"),
        "Altitude above takeoff [m]": _tag(t, "XMP:RelativeAltitude"),
        "Gimbal yaw [°]":           _tag(t, "XMP:GimbalYawDegree"),
        "Gimbal pitch [°]":         _tag(t, "XMP:GimbalPitchDegree"),
        "Gimbal roll [°]":          _tag(t, "XMP:GimbalRollDegree"),
        "RTK std. latitude [m]":    _tag(t, "XMP:RtkStdLat"),
        "RTK std. longitude [m]":   _tag(t, "XMP:RtkStdLon"),
        "RTK std. height [m]":      _tag(t, "XMP:RtkStdHgt"),
        "RTK status":               _tag(t, "XMP:RtkFlag"),
    }
    for k, v in pos.items():
        print(f"{k:28s} {v if v is not None else '– not found –'}")

    # Rough estimate (only for nadir images over flat terrain)
    height = pos["Altitude above takeoff [m]"]
    fx = float(str(t["XMP:DewarpData"]).split(";")[-1].split(",")[0])   # focal length in pixels
    if height is not None:
        height = float(height)
        h_px, w_px = capture["dn"][band].shape
        gsd = height / fx
        print(f"\nGround sampling distance (GSD) ≈ {100 * gsd:.2f} cm/pixel")
        print(f"Footprint on the ground ≈ {w_px * gsd:.1f} m × {h_px * gsd:.1f} m")
        print("(Assumptions: camera pointing straight down, ground at takeoff height)")

    # Optional: convert to UTM if pyproj is installed
    try:
        from pyproj import Transformer
        lat, lon = float(pos["Latitude [°]"]), float(pos["Longitude [°]"])
        zone = int((lon + 180) // 6) + 1
        epsg = 25800 + zone                     # ETRS89 / UTM, e.g. 25832 = zone 32N
        e, n = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform(lon, lat)
        print(f"\nCamera position in ETRS89/UTM {zone}N (EPSG:{epsg}): E = {e:.3f} m, N = {n:.3f} m")
    except ImportError:
        print("\n(For UTM coordinates: conda install -c conda-forge pyproj)")
    except (TypeError, ValueError):
        pass
    return pos


def show_position_tags(capture, band=None):
    """Lists all metadata entries related to position/attitude (if something is missing above)."""
    t = capture["tags"][band or REFERENCE_BAND]
    for k, v in t.items():
        if any(s in k.lower() for s in ("gps", "altitude", "yaw", "pitch", "roll", "rtk")):
            print(f"{k:40s} {v}")


# ---------- Georeferencing with ground control points (GCPs) ---------------

def lonlat_to_utm(lon, lat, zone=None):
    """ETRS89/GRS80 longitude/latitude (degrees) → UTM easting/northing (m), Krüger series (mm-accurate).
    No extra package needed. Returns (E, N, zone)."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    if zone is None:
        zone = int((np.mean(lon) + 180) // 6) + 1
    a, f = 6378137.0, 1 / 298.257222101           # GRS80 (ETRS89); WGS84 differs only in the 9th digit of f
    k0, E0 = 0.9996, 500000.0
    lon0 = np.radians(zone * 6 - 183)
    n = f / (2 - f)
    A = a / (1 + n) * (1 + n**2 / 4 + n**4 / 64)
    alpha = [n / 2 - 2 * n**2 / 3 + 5 * n**3 / 16 + 41 * n**4 / 180,
             13 * n**2 / 48 - 3 * n**3 / 5 + 557 * n**4 / 1440,
             61 * n**3 / 240 - 103 * n**4 / 140,
             49561 * n**4 / 161280]
    phi, lam = np.radians(lat), np.radians(lon) - lon0
    c = 2 * np.sqrt(n) / (1 + n)
    t = np.sinh(np.arctanh(np.sin(phi)) - c * np.arctanh(c * np.sin(phi)))
    xi = np.arctan2(t, np.cos(lam))
    eta = np.arctanh(np.sin(lam) / np.sqrt(1 + t**2))
    E = eta + sum(al * np.cos(2 * j * xi) * np.sinh(2 * j * eta) for j, al in enumerate(alpha, 1))
    N = xi + sum(al * np.sin(2 * j * xi) * np.cosh(2 * j * eta) for j, al in enumerate(alpha, 1))
    return E0 + k0 * A * E, k0 * A * N, zone


def utm_prj_wkt(zone):
    """ESRI WKT for ETRS89 / UTM zone N (written as .prj next to the raster)."""
    return ('PROJCS["ETRS89_UTM_zone_{z}N",GEOGCS["GCS_ETRS_1989",DATUM["D_ETRS_1989",'
            'SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],'
            'UNIT["Degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
            'PARAMETER["False_Easting",500000.0],PARAMETER["False_Northing",0.0],'
            'PARAMETER["Central_Meridian",{cm}],PARAMETER["Scale_Factor",0.9996],'
            'PARAMETER["Latitude_Of_Origin",0.0],UNIT["Meter",1.0]]').format(z=zone, cm=float(zone * 6 - 183))


def load_gcps(csv_path):
    """Reads a GCP CSV (e.g. Emlid Flow export). Uses Easting/Northing if filled, otherwise converts
    Longitude/Latitude (ETRS89) to UTM. Returns a DataFrame indexed by point name with columns E, N."""
    df = pd.read_csv(csv_path, sep=None, engine="python", dtype={"Name": str})
    df.columns = [c.strip() for c in df.columns]
    df["Name"] = df["Name"].astype(str).str.strip()
    df = df.set_index("Name")

    has_en = {"Easting", "Northing"} <= set(df.columns) and df[["Easting", "Northing"]].notna().all().all()
    if has_en:
        df["E"], df["N"] = df["Easting"].astype(float), df["Northing"].astype(float)
        zone = GCP_UTM_ZONE
        print("Using Easting/Northing from the CSV. Make sure GCP_UTM_ZONE / EPSG match the CSV's 'CS name'.")
    else:
        lon, lat = df["Longitude"].astype(float), df["Latitude"].astype(float)
        if not (lon.between(-180, 180).all() and lat.between(-90, 90).all()):
            raise ValueError("Longitude/Latitude out of range – check the CSV's decimal separator.")
        E, N, zone = lonlat_to_utm(lon.values, lat.values, GCP_UTM_ZONE)
        df["E"], df["N"] = E, N
        print(f"Converted Longitude/Latitude → ETRS89 / UTM zone {zone}N (EPSG:{25800 + zone}).")

    # Warn about points measured (almost) at the same spot
    names = list(df.index)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            d = np.hypot(df.loc[names[i], "E"] - df.loc[names[j], "E"], df.loc[names[i], "N"] - df.loc[names[j], "N"])
            if d < 0.05:
                print(f"⚠ Points {names[i]} and {names[j]} are only {100 * d:.1f} cm apart "
                      f"(same target measured twice?) – use only one of them, or click both on the same spot.")
    df.attrs["zone"] = zone
    return df


def _click_point(window, img):
    """Click ONE point. Left click = set/move, ENTER = confirm, s or ESC = skip this point."""
    point = []

    def mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            point[:] = [(x, y)]

    colour = img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, mouse)
    while True:
        view = colour.copy()
        if point:
            x, y = point[0]
            cv2.drawMarker(view, (x, y), (0, 0, 255), cv2.MARKER_CROSS, 40, 2)
            cv2.circle(view, (x, y), 4, (0, 255, 255), -1)
        cv2.putText(view, "click = target centre  |  ENTER = confirm  |  s / ESC = skip point",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.imshow(window, view)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10) and point:
            break
        if key in (27, ord("s")):
            point = []
            break
    cv2.destroyWindow(window)
    for _ in range(10):
        cv2.waitKey(1)
    return point[0] if point else None


def mark_gcps(capture, gcps, band=None, max_width=1400, zoom_width=900, existing=None):
    """For every GCP in the CSV: 1) drag a rough box around the target (c = skip),
    2) click the exact target centre in the zoom. Returns {name: (x, y)} in pixels of the aligned image."""
    band = band or REFERENCE_BAND
    view = _display_8bit(capture["dn"][band], capture["valid"][band])
    h, w = view.shape
    s = min(1.0, max_width / w)
    pixels = dict(existing or {})

    for name in gcps.index:
        # overview with already marked points
        small = cv2.cvtColor(cv2.resize(view, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2BGR)
        for n, (px, py) in pixels.items():
            cv2.drawMarker(small, (int(px * s), int(py * s)), (0, 0, 255), cv2.MARKER_CROSS, 14, 2)
            cv2.putText(small, str(n), (int(px * s) + 6, int(py * s) - 6), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 255, 255), 1, cv2.LINE_AA)
        short = str(name).encode("ascii", "ignore").decode()
        x, y, bw, bh = _select_roi(f"GCP {short}: rough box - ENTER (c = skip)", small)
        if bw == 0 or bh == 0:
            print(f"GCP {name}: skipped")
            continue
        x0, y0 = int(x / s), int(y / s)
        x1, y1 = min(w, int((x + bw) / s) + 1), min(h, int((y + bh) / s) + 1)

        crop = view[y0:y1, x0:x1]
        z = zoom_width / crop.shape[1]
        large = cv2.resize(crop, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
        p = _click_point(f"GCP {short}: click target centre", large)
        if p is None:
            print(f"GCP {name}: skipped")
            continue
        pixels[name] = (x0 + p[0] / z - 0.5, y0 + p[1] / z - 0.5)
        print(f"GCP {name}: x = {pixels[name][0]:.1f}, y = {pixels[name][1]:.1f}")
    return pixels


def _apply_h(H, pts):
    pts = np.asarray(pts, float)
    q = np.c_[pts, np.ones(len(pts))] @ H.T
    return q[:, :2] / q[:, 2:3]


def _fit_h(src, dst, kind):
    """Least-squares transform pixel → map. kind: 'homography' (≥4 points) or 'affine' (≥3 points)."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    ms, md = src.mean(axis=0), dst.mean(axis=0)            # centre the coordinates (numerical stability)
    s0, d0 = src - ms, dst - md
    if kind == "homography":
        Hn, _ = cv2.findHomography(s0, d0, 0)
        if Hn is None:
            raise RuntimeError("Homography could not be computed (points collinear?).")
    else:
        X = np.c_[s0, np.ones(len(s0))]
        coef, *_ = np.linalg.lstsq(X, d0, rcond=None)
        Hn = np.vstack([coef.T, [0, 0, 1]])
    Ts = np.array([[1, 0, -ms[0]], [0, 1, -ms[1]], [0, 0, 1]])
    Td = np.array([[1, 0, md[0]], [0, 1, md[1]], [0, 0, 1]])
    return Td @ Hn @ Ts


def fit_georeference(gcp_pixels, gcps, kind="homography", check_points=()):
    """Fits pixel → UTM with the control points, reports residuals, RMSE, leave-one-out RMSE
    and the error at independent check points."""
    names = [n for n in gcps.index if n in gcp_pixels]
    control = [n for n in names if n not in check_points]
    check = [n for n in names if n in check_points]
    need = 4 if kind == "homography" else 3
    if len(control) < need:
        raise ValueError(f"'{kind}' needs at least {need} control points, have {len(control)}: {control}")

    src = np.array([gcp_pixels[n] for n in control])
    dst = gcps.loc[control, ["E", "N"]].values
    H = _fit_h(src, dst, kind)

    rows = []
    for n in names:
        pred = _apply_h(H, [gcp_pixels[n]])[0]
        dE, dN = pred - gcps.loc[n, ["E", "N"]].values.astype(float)
        loo = np.nan
        if n in control and len(control) - 1 >= need:
            others = [m for m in control if m != n]
            H_loo = _fit_h([gcp_pixels[m] for m in others], gcps.loc[others, ["E", "N"]].values, kind)
            p2 = _apply_h(H_loo, [gcp_pixels[n]])[0]
            loo = np.hypot(*(p2 - gcps.loc[n, ["E", "N"]].values.astype(float)))
        rows.append({"GCP": n, "Role": "control" if n in control else "check",
                     "x [px]": gcp_pixels[n][0], "y [px]": gcp_pixels[n][1],
                     "dE [cm]": 100 * dE, "dN [cm]": 100 * dN, "Error [cm]": 100 * np.hypot(dE, dN),
                     "Leave-one-out [cm]": 100 * loo})
    table = pd.DataFrame(rows).set_index("GCP")

    def rmse(sel):
        v = table.loc[table["Role"] == sel, "Error [cm]"]
        return np.sqrt(np.mean(v ** 2)) if len(v) else np.nan

    c = np.mean(src, axis=0)                                  # pixel size at the image centre of the GCPs
    p0, px_, py_ = _apply_h(H, [c, c + [1, 0], c + [0, 1]])
    u, v = px_ - p0, py_ - p0
    gsd = np.sqrt(abs(u[0] * v[1] - u[1] * v[0]))           # metres per pixel
    print(f"Transform: {kind} with {len(control)} control point(s), {len(check)} check point(s)")
    print(f"Pixel size ≈ {100 * gsd:.2f} cm")
    print(f"RMSE control points:  {rmse('control'):.1f} cm"
          + ("   (= 0 with exactly 4 points for a homography – not meaningful!)" if len(control) == need else ""))
    loo = table["Leave-one-out [cm]"].dropna()
    if len(loo):
        print(f"RMSE leave-one-out:   {np.sqrt(np.mean(loo ** 2)):.1f} cm   ← realistic accuracy estimate"
              + ("  (only 1 point more than the minimum → very pessimistic, use ≥6–8 points)"
                 if len(control) == need + 1 else ""))
    if check:
        print(f"RMSE check points:    {rmse('check'):.1f} cm   ← independent accuracy")
    return {"H": H, "kind": kind, "table": table, "gsd": gsd, "zone": gcps.attrs.get("zone")}


def georeference_rasters(rasters, georef, resolution=None):
    """Resamples image-space rasters (dict name → 2D array) onto a north-up UTM grid.
    Returns (dict name → 2D array, grid) with grid = dict(E0, N0, res, width, height, zone)."""
    H = georef["H"]
    first = next(iter(rasters.values()))
    h, w = first.shape
    res = resolution or georef["gsd"]
    corners = _apply_h(H, [(-0.5, -0.5), (w - 0.5, -0.5), (w - 0.5, h - 0.5), (-0.5, h - 0.5)])
    E0, N0 = np.floor(corners[:, 0].min() / res) * res, np.ceil(corners[:, 1].max() / res) * res
    E1, N1 = np.ceil(corners[:, 0].max() / res) * res, np.floor(corners[:, 1].min() / res) * res
    W, Hh = int(round((E1 - E0) / res)), int(round((N0 - N1) / res))

    # output pixel (col, row) → map (E, N) → image pixel
    G = np.array([[res, 0, E0 + res / 2], [0, -res, N0 - res / 2], [0, 0, 1]])
    M = np.linalg.inv(H) @ G
    out = {}
    for name, arr in rasters.items():
        out[name] = cv2.warpPerspective(arr.astype("float32"), M, (W, Hh),
                                        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                        borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
    grid = {"E0": E0, "N0": N0, "res": res, "width": W, "height": Hh, "zone": georef["zone"]}
    return out, grid


def write_geotiff(path, rasters, grid):
    """Writes a multi-band float32 GeoTIFF (rasterio). Without rasterio: one TIFF per band
    + world file (.tfw) + projection (.prj), which QGIS/ArcGIS read as well."""
    names = list(rasters)
    epsg = 25800 + grid["zone"]
    try:
        import rasterio
        from rasterio.transform import from_origin
        with rasterio.open(path, "w", driver="GTiff", width=grid["width"], height=grid["height"],
                           count=len(names), dtype="float32", crs=f"EPSG:{epsg}", nodata=np.nan,
                           transform=from_origin(grid["E0"], grid["N0"], grid["res"], grid["res"]),
                           compress="deflate") as dst:
            for i, n in enumerate(names, 1):
                dst.write(rasters[n].astype("float32"), i)
                dst.set_band_description(i, n)
        print(f"GeoTIFF written: {path}  (bands: {', '.join(names)}, EPSG:{epsg})")
    except ImportError:
        base = os.path.splitext(path)[0]
        for n in names:
            p = f"{base}_{n}.tif"
            cv2.imwrite(p, rasters[n].astype("float32"))
            with open(f"{base}_{n}.tfw", "w") as f:
                f.write(f"{grid['res']}\n0\n0\n{-grid['res']}\n"
                        f"{grid['E0'] + grid['res'] / 2}\n{grid['N0'] - grid['res'] / 2}\n")
            with open(f"{base}_{n}.prj", "w") as f:
                f.write(utm_prj_wkt(grid["zone"]))
            print(f"written: {p} + .tfw + .prj (EPSG:{epsg})")
        print("(For a single multi-band GeoTIFF: conda install -c conda-forge rasterio)")


def show_georef_check(capture, gcps, gcp_pixels, georef, band=None, panel_polygons=None, arrow_scale=50):
    """Left: image with pixel axes, panels and GCPs. Right: GCP layout in UTM with residual vectors."""
    band = band or REFERENCE_BAND
    view = _display_8bit(capture["dn"][band], capture["valid"][band])
    tab = georef["table"] if georef else None
    fig, ax = plt.subplots(1, 2, figsize=(17, 6.5))

    ax[0].imshow(view, cmap="gray")
    for name, poly in (panel_polygons or {}).items():
        ax[0].add_patch(plt.Polygon(np.asarray(poly), fill=False, color="orange", lw=1.5))
        ax[0].annotate(name, np.asarray(poly).mean(axis=0), color="orange", fontsize=9)
    for n, (x, y) in gcp_pixels.items():
        role = tab.loc[n, "Role"] if tab is not None and n in tab.index else "control"
        ax[0].plot(x, y, "+" if role == "control" else "x", color="red" if role == "control" else "cyan",
                   ms=12, mew=2)
        ax[0].annotate(str(n), (x, y), xytext=(6, -6), textcoords="offset points", color="yellow", fontsize=10)
    ax[0].set_xlabel("x [px]"); ax[0].set_ylabel("y [px]")
    ax[0].set_title(f"{band} – image coordinates (orange = panels, red + = control, cyan × = check)")

    E, N = gcps["E"].values, gcps["N"].values
    e0, n0 = np.floor(E.min()), np.floor(N.min())
    ax[1].scatter(E - e0, N - n0, color="black", zorder=3)
    for name in gcps.index:
        ax[1].annotate(str(name), (gcps.loc[name, "E"] - e0, gcps.loc[name, "N"] - n0),
                       xytext=(5, 5), textcoords="offset points")
        if tab is not None and name in tab.index:
            ax[1].arrow(gcps.loc[name, "E"] - e0, gcps.loc[name, "N"] - n0,
                        tab.loc[name, "dE [cm]"] / 100 * arrow_scale, tab.loc[name, "dN [cm]"] / 100 * arrow_scale,
                        color="red", width=0.02, length_includes_head=True)
    ax[1].set_aspect("equal")
    ax[1].set_xlabel(f"Easting − {e0:.0f} [m]"); ax[1].set_ylabel(f"Northing − {n0:.0f} [m]")
    ax[1].set_title(f"GCPs in UTM (red arrows = residuals, {arrow_scale}× enlarged)")
    ax[1].grid(alpha=0.3)
    plt.tight_layout()
    plt.show()


def show_georeferenced(rasters, grid, gcps=None, keys=None):
    """Shows georeferenced rasters with Easting/Northing axes."""
    keys = keys or list(rasters)
    ext = [grid["E0"], grid["E0"] + grid["width"] * grid["res"],
           grid["N0"] - grid["height"] * grid["res"], grid["N0"]]
    fig, ax = plt.subplots(1, len(keys), figsize=(5.5 * len(keys), 5))
    ax = np.atleast_1d(ax)
    for a, k in zip(ax, keys):
        if k.upper() == "NDVI":
            im = a.imshow(rasters[k], extent=ext, cmap="RdYlGn", vmin=-0.2, vmax=1)
        else:
            cmap = band_cmap(k) if k in BAND_COLOURS else "gray"
            im = a.imshow(rasters[k], extent=ext, cmap=cmap, vmin=0, vmax=np.nanpercentile(rasters[k], 99))
        plt.colorbar(im, ax=a, fraction=0.035)
        if gcps is not None:
            a.scatter(gcps["E"], gcps["N"], marker="+", color="red", s=60)
        a.set_title(k)
        a.set_xlabel(f"Easting [m] (UTM {grid['zone']}N)"); a.set_ylabel("Northing [m]")
        a.ticklabel_format(useOffset=False, style="plain")
        a.tick_params(axis="x", labelrotation=30)
    plt.tight_layout()
    plt.show()


def show_reflectance(reflectance, ndvi=None):
    """Reflectance of all bands (band colour scales) and optionally the NDVI, in image coordinates."""
    n = len(BANDS) + (ndvi is not None)
    fig, ax = plt.subplots(1, n, figsize=(6 * n, 5))
    for a, band in zip(ax, BANDS):
        im = a.imshow(reflectance[band], cmap=band_cmap(band), vmin=0,
                      vmax=np.nanpercentile(reflectance[band], 99))
        a.set_title(f"{band} – reflectance"); a.set_xlabel("x [px]"); a.set_ylabel("y [px]")
        plt.colorbar(im, ax=a, fraction=0.035, label="Reflectance")
    if ndvi is not None:
        im = ax[-1].imshow(ndvi, cmap="RdYlGn", vmin=-0.2, vmax=1)
        ax[-1].set_title("NDVI"); ax[-1].set_xlabel("x [px]"); ax[-1].set_ylabel("y [px]")
        plt.colorbar(im, ax=ax[-1], fraction=0.035, label="NDVI")
    plt.tight_layout()
    plt.show()
