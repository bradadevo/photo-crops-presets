"""Tests never touch your real AllProPhoto settings, marks or caches: the whole run uses a folder of
its own (set before the app's modules are loaded, so every path they pick is inside it)."""
import os
import tempfile

os.environ["ALLPROPHOTO_STATE"] = tempfile.mkdtemp(prefix="allprophoto-tests-")
