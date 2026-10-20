"""Use the service Python and a disposable cache; never contend with the live writer."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config

with tempfile.TemporaryDirectory(prefix='stock-activity-tests-') as directory:
    original = config.CACHE_DIR
    for name, value in list(vars(config).items()):
        if isinstance(value, Path):
            try:
                relative = value.relative_to(original)
            except ValueError:
                continue
            setattr(config, name, Path(directory) / relative)
    suite = unittest.defaultTestLoader.discover(str(ROOT), pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    import scan_cache
    for connection in scan_cache._connections.values():
        connection.close()
    scan_cache._connections.clear()
sys.exit(not result.wasSuccessful())
