"""Isolate mutable runtime cache/locks from the running desktop service."""
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
config.CACHE_DIR=Path(__file__).parent/'isolated_test_cache';config.CACHE_DIR.mkdir(exist_ok=True)
suite=unittest.defaultTestLoader.discover(str(ROOT),pattern='test_*.py')
result=unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not result.wasSuccessful())
