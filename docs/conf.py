from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

project = "HorRAGor"
author = "HorRAGor maintainers"
release = "3.0.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinxcontrib.mermaid",
]

autosummary_generate = True
autodoc_typehints = "description"
autodoc_member_order = "bysource"
autodoc_mock_imports = ["openvino_genai", "polars", "pyspark", "selenium", "supabase"]

exclude_patterns = ["_build"]
html_theme = "sphinx_rtd_theme"
html_static_path: list[str] = []
html_title = "HorRAGor Technical Documentation"
