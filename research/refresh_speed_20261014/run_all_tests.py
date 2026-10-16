import sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config
with TemporaryDirectory() as tmp,patch.object(config,'CACHE_DIR',Path(tmp)):
    try:
        suite=unittest.defaultTestLoader.discover(str(config.ROOT),pattern='test_*.py')
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    finally:
        import scan_cache
        scan_cache.flush()
        with scan_cache._lock:
            for key in list(scan_cache._connections):
                if Path(key).parent==Path(tmp):
                    scan_cache._connections.pop(key).close()
sys.exit(0 if result.wasSuccessful() else 1)
