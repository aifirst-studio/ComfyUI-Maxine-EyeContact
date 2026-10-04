import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PACKAGE))
import activity
spec=importlib.util.spec_from_file_location('start_service',PACKAGE/'service/start_service.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class StartTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'.env').write_text('NGC_API_KEY=test-only\n')
        (self.root/'image.json').write_text(json.dumps({'digest':'nvcr.io/nim/nvidia/maxine-eye-contact@sha256:test'}))
        self.calls=[]
        def fake_run(command,**kwargs):
            self.calls.append(command)
            return subprocess.CompletedProcess(command,0,'RTX 3090\n' if command[0]=='nvidia-smi' else '', '')
        self.patches=[patch.object(m,'ROOT',self.root),patch.object(activity,'LOCK_PATH',self.root/'activity.lock'),
                      patch.object(m.sys, 'platform', 'linux'),
                      patch.object(m,'require_idle_comfy'),patch.object(m.subprocess,'run',side_effect=fake_run),
                      patch.object(m.subprocess,'check_output',return_value=json.dumps(['nvcr.io/nim/nvidia/maxine-eye-contact@sha256:test']))]
        for item in self.patches:item.start()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def test_busy_queue_never_touches_gpu_or_docker(self):
        m.require_idle_comfy.side_effect=RuntimeError('busy')
        with self.assertRaisesRegex(RuntimeError,'busy'):m.start(True)
        self.assertEqual(self.calls,[])

    def test_cached_image_does_not_pull(self):
        m.start(True)
        self.assertFalse(any('pull' in args for args in self.calls))
        up=next(args for args in self.calls if 'up' in args)
        self.assertIn('never',up)
        self.assertEqual(up[-1],'eye-contact')

    def test_new_jobs_prevent_container_start(self):
        m.require_idle_comfy.side_effect=[None,RuntimeError('new job')]
        with self.assertRaisesRegex(RuntimeError,'new job'):m.start(True)
        self.assertFalse(any('up' in args for args in self.calls))

    def test_missing_image_in_console_does_not_download(self):
        def fake(command,**kwargs):
            self.calls.append(command)
            return subprocess.CompletedProcess(command,1 if command[:3]==['docker','image','inspect'] else 0,'RTX 3090\n','')
        m.subprocess.run.side_effect=fake
        with self.assertRaisesRegex(RuntimeError,'image is missing'):m.start(True)
        self.assertFalse(any('pull' in args or 'up' in args for args in self.calls))

    def test_gpu_absent_prevents_docker_start(self):
        m.subprocess.run.return_value=subprocess.CompletedProcess([],1,'','no GPU')
        m.subprocess.run.side_effect=None
        with self.assertRaisesRegex(RuntimeError,'not available on Linux'):m.start(True)

    def test_explicit_update_pulls_latest_even_if_cached(self):
        m.start(update_image=True)
        self.assertTrue(any(args[-2:] == ['pull', 'eye-contact'] for args in self.calls))

    def test_service_helper_rejects_native_windows(self):
        with patch.object(m.sys, 'platform', 'win32'):
            with self.assertRaisesRegex(RuntimeError, 'Linux host'):
                m.start()
        self.assertFalse(self.calls)


if __name__=='__main__':unittest.main(verbosity=2)
