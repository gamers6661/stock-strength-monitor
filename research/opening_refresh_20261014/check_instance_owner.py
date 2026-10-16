"""Check the live service's OS lock without starting another service."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import serve
with serve.service_instance_lock() as owner:
    assert not owner, 'live service did not retain the workspace lock'
print('PASS: live service owns the workspace lock; competing owner rejected')
