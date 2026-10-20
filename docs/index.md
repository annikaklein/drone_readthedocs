# Multispectral Reflectance Processing

**Processing Pipeline & Field Guide — DJI Mavic 3 Multispectral (M3M)**
Single-capture panel calibration (ELM), band alignment and optional GCP georeferencing.

*Annika Klein, Neele Hühnerbein*

This documentation describes the multispectral processing pipeline implemented in the
module `m3m_processing.py` and the notebook `MS_Calibration_Panel_EN.ipynb`: what is done
in each step, with which formula, where the formula comes from, and why it is done this way.
The goal is a **surface-reflectance product (0–1 per band)** from single Mavic 3M captures in
which a calibrated reflectance panel is visible.

:::{admonition} Open tasks (validation status)
:class: warning

- **Verify spectral values.** Reflectance values were inspected individually for typical
  surfaces (asphalt, concrete, grass) and compared with literature spectra. Spectral shapes and
  magnitudes are plausible; remaining deviations (slightly high G values, possibly due to partial
  panel saturation, and NIR values for grass at the upper end of the literature range) still need
  to be checked with several samples per surface type and a measured spectral library.
- **Verify GCP georeferencing.** The GCP-based georeferencing (homography/affine fit, RMSE,
  leave-one-out) has so far only been tested with few, partly duplicate points. It needs to be
  validated in the next field campaign with 6–8 well-distributed GCPs and at least two
  independent check points.
- **Verify 2-point calibration.** The 2-point ELM is implemented but has not yet been tested with
  real data, since only one calibrated panel was available. A dark panel (5–10 % reflectance)
  should be added in the next campaign.
:::

## Where to start

- **New here?** Read the {doc}`quickstart` and the {doc}`overview`.
- **Want the maths?** See {doc}`steps` — every formula with source and reasoning.
- **Going into the field?** Print the {doc}`field_checklist`.
- **Looking for a function?** See the {doc}`api`.

```{toctree}
:maxdepth: 2
:caption: User guide

quickstart
overview
steps
metadata
field_checklist
```

```{toctree}
:maxdepth: 2
:caption: Reference

notebook_usage
api
notation
references
```
