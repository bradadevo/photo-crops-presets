"""Tests never touch your real VS Digital Pro settings, marks or caches: the whole run uses a folder of
its own (set before the app's modules are loaded, so every path they pick is inside it)."""
import os
import tempfile

os.environ["VSDP_AI_ENLARGE"] = "0"  # (plain enlarging: fast, no model download)
os.environ["ALLPROPHOTO_STATE"] = tempfile.mkdtemp(prefix="vsdigitalpro-tests-")
