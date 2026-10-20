# Sphinx configuration for the M3M processing documentation
import os
import sys

# Make m3m_processing.py (repository root) importable for autodoc
sys.path.insert(0, os.path.abspath(".."))

project = "M3M Multispectral Reflectance Processing"
author = "Annika Klein, Neele Hühnerbein"
copyright = "2026, Annika Klein, Neele Hühnerbein"
release = "1.0"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.mathjax",
    "sphinxcontrib.mermaid",
]

# Heavy / optional dependencies are mocked so the API reference builds on Read the Docs
autodoc_mock_imports = ["cv2", "exiftool", "rasterio", "pyproj", "tifffile",
                        "matplotlib", "numpy", "pandas"]
autodoc_member_order = "bysource"
autodoc_default_options = {"members": True, "undoc-members": True}

myst_enable_extensions = ["dollarmath", "amsmath", "colon_fence", "deflist", "attrs_inline"]
myst_heading_anchors = 3

source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
exclude_patterns = ["_build"]

html_theme = "sphinx_rtd_theme"
html_title = "M3M Reflectance Processing"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_theme_options = {"navigation_depth": 3, "collapse_navigation": False}
