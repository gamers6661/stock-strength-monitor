"""The workspace service stays single even if its HTTP probe is slow."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import serve


class ServiceInstanceTests(unittest.TestCase):
    def test_second_owner_is_rejected_and_release_allows_restart(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'instance.lock'
            with serve.service_instance_lock(path) as first:
                self.assertTrue(first)
                with serve.service_instance_lock(path) as second:
                    self.assertFalse(second)
            with serve.service_instance_lock(path) as restarted:
                self.assertTrue(restarted)

    def test_busy_service_does_not_probe_or_bind_another_port(self):
        @contextmanager
        def busy():
            yield False
        with patch.object(serve,'service_instance_lock',busy), \
             patch.object(serve.sys,'argv',['serve.py','--no-browser']), \
             patch.object(serve,'probe_alive') as probe, \
             patch.object(serve,'bind_server') as bind, \
             patch.object(serve,'run_service') as run:
            serve.main()
        probe.assert_not_called()
        bind.assert_not_called()
        run.assert_not_called()

    def test_owner_retains_lock_for_entire_service_lifetime(self):
        events=[]
        @contextmanager
        def owner():
            events.append('acquired')
            yield True
            events.append('released')
        def run():
            self.assertEqual(events,['acquired'])
            events.append('running')
        with patch.object(serve,'service_instance_lock',owner),patch.object(serve,'run_service',run):
            serve.main()
        self.assertEqual(events,['acquired','running','released'])


if __name__=='__main__':
    unittest.main()
