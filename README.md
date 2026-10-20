# M3M Multispectral Reflectance Processing

Processing pipeline for DJI Mavic 3 Multispectral (M3M) captures: radiometric and
geometric correction, band alignment, panel calibration (Empirical Line Method) and
optional GCP georeferencing.

Documentation: built with Sphinx and hosted on Read the Docs (see `docs/`).

## Build the docs locally

```bash
pip install -r docs/requirements.txt
sphinx-build -b html docs docs/_build/html
# open docs/_build/html/index.html
```

## Publish on Read the Docs

1. Push this repository to GitHub/GitLab (`.readthedocs.yaml` must be in the root).
2. Log in at <https://readthedocs.org>, choose **Import a Project** and select the repository.
3. Every push to the default branch rebuilds the documentation automatically.
