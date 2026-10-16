"""Run the refresh tests with a separate writer lock from the live market scan."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config
with TemporaryDirectory() as tmp, patch.object(config,'CACHE_DIR',Path(tmp)):
    suite=unittest.defaultTestLoader.loadTestsFromNames(
        ['test_service_instance','test_refresh_boundary','test_scan_performance'])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
