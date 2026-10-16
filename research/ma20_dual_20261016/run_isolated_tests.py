"""Run repository tests without sharing the live service's cache or write lock."""
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import config

with tempfile.TemporaryDirectory(prefix='ma20-regression-') as folder:
    old_cache=config.CACHE_DIR
    for name,value in list(vars(config).items()):
        if isinstance(value,Path) and value.is_relative_to(old_cache):
            setattr(config,name,Path(folder)/value.relative_to(old_cache))
    config.CACHE_DIR.mkdir(parents=True,exist_ok=True)
    suite=unittest.defaultTestLoader.discover(str(ROOT),pattern='test_*.py',top_level_dir=str(ROOT))
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    import scan_cache
    for connection in scan_cache._connections.values():connection.close()
    scan_cache._connections.clear()
    sys.exit(not result.wasSuccessful())
