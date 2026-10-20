# Field Checklist

What has to be prepared and recorded in the field so that the data can be processed with this
pipeline.

## Equipment

- DJI Mavic 3M with RTK module (network RTK/NTRIP credentials, e.g. SAPOS VRS), charged
  batteries, spare propellers, formatted SD card(s).
- Calibrated reflectance panel(s) with certificate giving the reflectance at 560, 650, 730 and
  860 nm. Recommended: one **dark** (5–10 %) and one **bright/grey** (20–50 %) panel for the
  2-point ELM. Very bright (white) panels tend to saturate (observed in the G band).
- Panel size: at least ≈ 20 clean pixels across after shrinking, i.e. ≥ 25 · GSD
  (e.g. ≥ 40 cm at 1.5 cm GSD).
- GNSS rover (e.g. Emlid Reach RS2+/RS3) with pole/bipod and NTRIP correction; known antenna
  height.
- GCP targets: 6–8 high-contrast (black/white checkerboard) targets, ≥ 30 cm, flat and fixed
  against wind.
- Field sheet, pen, phone/camera for documentation photos, measuring tape, soft brush/cloth for
  the panels, dark clothing.

## Before the flight

- Weather: clear sky or uniform overcast; avoid broken clouds (changing illumination). Low wind.
- Time: ideally within ±2 h of solar noon, solar elevation ≥ 30°. Be aware of sunglint on water
  surfaces!
- Sunlight sensor clean and unobstructed; firmware up to date.
- Gimbal at −90° (nadir); flight altitude and resulting GSD noted; RTK status **fixed** before
  take-off.

## Placing the panels

- Flat and horizontal, on open ground; no shadows from objects, trees or people; keep a distance
  of at least twice the height of nearby objects; avoid bright walls or vehicles next to it.
- Preferably near the image centre (smaller vignetting and distortion).
- Do not touch the reflecting surface; keep it dry and clean; no one standing next to the panel
  during capture.
- Ensure the panel is visible in every capture to be processed (single-capture workflow), or
  capture it before *and* after the flight.
- If possible, check on site that the panel is not saturated in any band.

## Ground control points

- Distribute over the whole image footprint: all four corners and the centre; keep 2 targets as
  independent check points.
- Measure the target centre with a **fixed** RTK solution; note the antenna height and averaging
  time.
- One measurement per target and a unique ID; do not store repeated measurements of the same
  target as separate points (or mark them as repeats).
- Photograph each target together with its ID.
- Note the coordinate system (ETRS89/UTM 32N, EPSG:25832) and height reference.

## What to record (field log)

- Date, start/end time (with time zone), site, operator(s).
- Weather: cloud cover (oktas), changes in illumination during the flight, wind, temperature.
- Flight parameters: altitude, GSD, speed, overlap, drone and camera serial numbers, firmware
  version, RTK status/mount point.
- Panel IDs, certificate file, positions, and the image numbers in which they appear.
- GCP IDs, rover model, base/NTRIP mount point, CSV file name.
- Disturbances: shadows, people, vehicles, wet surfaces, dew.
- Ground truth notes: surface/vegetation type, height, condition, photos.

## After the flight

- Back up SD card and rover data on site.
- Export the rover CSV directly from the app; do **not** open and re-save it in a spreadsheet
  program (locale settings may corrupt decimal separators).
- Check `RtkFlag`/`SurveyingMode` of the images and panel saturation before leaving the site, so
  that captures can be repeated if necessary.
