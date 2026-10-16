import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import config
with tempfile.TemporaryDirectory(prefix='closing-judgment-tests-') as d:
    config.CACHE_DIR=Path(d)
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_closing_judgment','test_market_strength','test_market_strength_rework','test_closing_archive_recovery','test_ma_trend','test_relay_cycles','test_emotion_relay','test_relay_pools','test_emotion_ui'])
    result=unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
