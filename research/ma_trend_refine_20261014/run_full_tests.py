"""Keep unit-test pipeline locks separate from the running market scanner."""
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
with tempfile.TemporaryDirectory(prefix='ma-trend-test-') as directory:
    config.CACHE_DIR=Path(directory)
    suite=unittest.defaultTestLoader.discover(str(ROOT),pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    import scan_cache
    for connection in scan_cache._connections.values():connection.close()
    scan_cache._connections.clear()
    exit_code=0 if result.wasSuccessful() else 1
sys.exit(exit_code)
