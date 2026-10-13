from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import activity
import auto_service as m


@contextmanager
def unlocked(**kwargs):
    yield


class ConfigurationTests(unittest.TestCase):
    def test_disabled_by_default(self):
        self.assertIsNone(m.settings({}))
        with patch.object(m, 'require_local_docker') as docker:
            with m.managed_service({}):
                pass
            docker.assert_not_called()

    def test_windows_cannot_control_tunnel_host(self):
        with patch.object(m.sys, 'platform', 'win32'):
            with self.assertRaisesRegex(RuntimeError, 'same Linux host'):
                m.settings({'auto_service': {'enabled': True}})

    def test_invalid_config_does_not_silently_enable_automation(self):
        for options in (True, {'enabled': 'false'}):
            with self.assertRaises(ValueError):
                m.settings({'auto_service': options})

    def test_timeouts_default_to_ten_minutes(self):
        with patch.object(m.sys, 'platform', 'linux'):
            self.assertEqual(m.settings({'auto_service': {'enabled': True}}),
                             {'idle_timeout_seconds': 600, 'startup_timeout_seconds': 600})

    def test_remote_docker_is_rejected(self):
        with patch.dict(m.os.environ, {'DOCKER_HOST': 'ssh://remote-host'}):
            with self.assertRaisesRegex(RuntimeError, 'local Linux Docker socket'):
                m.require_local_docker()

    def test_remote_context_cannot_override_a_local_docker_host(self):
        with patch.dict(m.os.environ, {'DOCKER_HOST': 'unix:///var/run/docker.sock', 'DOCKER_CONTEXT': 'remote'}), \
                patch.object(m.subprocess, 'check_output', return_value='"ssh://remote-host"'):
            with self.assertRaises(RuntimeError):
                m.require_local_docker()

    def test_automatic_queue_url_must_be_local(self):
        with patch.object(m.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(ValueError, 'local ComfyUI queue'):
                m.settings({'auto_service': {'enabled': True}, 'comfy_url': 'https://remote.example'})

    def test_foreign_container_cannot_be_adopted(self):
        info = {'id': 'other', 'started_at': 'start', 'status': 'running', 'labels': {
            'com.docker.compose.project': 'someone-else', 'com.docker.compose.service': 'eye-contact',
            'com.docker.compose.project.working_dir': str(m.SERVICE)}}
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(info))):
            with self.assertRaisesRegex(RuntimeError, 'another installation'):
                m.container_info()

    def test_own_execution_can_start_with_pending_jobs(self):
        queue = {'queue_running': [[1, 'own-id', {}]], 'queue_pending': [[2, 'later-id', {}]]}
        with patch.object(m.start_service, 'comfy_queue', return_value=queue):
            m.require_job('own-id')
            with self.assertRaisesRegex(RuntimeError, 'Another ComfyUI job'):
                m.require_job('different-id')
            with self.assertRaises(RuntimeError):
                m.require_job(None)

    def test_pending_queue_cannot_start_without_active_own_execution(self):
        with patch.object(m.start_service, 'comfy_queue', return_value={'queue_running': [], 'queue_pending': [[1, 'id']]}):
            with self.assertRaises(RuntimeError):
                m.require_job('id')


class IdleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.info = {'id': 'owned-container', 'started_at': 'original-start', 'status': 'running'}
        self.config = {'auto_service': {'enabled': True, 'idle_timeout_seconds': 600}}
        self.patches = [patch.object(m, 'SERVICE', self.root), patch.object(m, 'STATE', self.root / 'auto-state.json'),
                        patch.object(m.sys, 'platform', 'linux'), patch.object(m, 'service_activity', unlocked),
                        patch.object(m, 'container_info', return_value=self.info),
                        patch.object(m.start_service, 'comfy_queue', return_value={'queue_running': [], 'queue_pending': []}),
                        patch.object(m.subprocess, 'run'), patch.object(m.time, 'time', return_value=1000)]
        for p in self.patches:
            p.start()
        m.save_state({'instance': m.instance(self.info), 'last_activity': 100})
        self.monitor = m.IdleMonitor()
        self.monitor.last_busy = 100

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_stops_only_owned_instance_after_idle_timeout(self):
        self.assertTrue(self.monitor.tick(self.config))
        self.assertEqual(m.subprocess.run.call_args.args[0], ['docker', 'stop', '--time', '45', 'owned-container'])
        self.assertFalse(m.STATE.exists())

    def test_recent_job_keeps_service_warm(self):
        m.save_state({'instance': m.instance(self.info), 'last_activity': 900})
        self.monitor.tick(self.config)
        m.subprocess.run.assert_not_called()

    def test_running_and_pending_jobs_reset_idle_clock(self):
        for queue in ({'queue_running': [[1, 'id']], 'queue_pending': []},
                      {'queue_running': [], 'queue_pending': [[2, 'id']]}):
            m.start_service.comfy_queue.return_value = queue
            self.monitor.tick(self.config)
            self.assertEqual(self.monitor.last_busy, 1000)
        m.subprocess.run.assert_not_called()

    def test_restarted_container_is_not_stopped(self):
        self.info['started_at'] = 'manual-restart'
        self.monitor.tick(self.config)
        m.subprocess.run.assert_not_called()
        self.assertFalse(m.STATE.exists())

    def test_replaced_container_is_not_stopped(self):
        self.info['id'] = 'other-container'
        self.monitor.tick(self.config)
        m.subprocess.run.assert_not_called()

    def test_unreachable_comfy_fails_closed(self):
        m.start_service.comfy_queue.side_effect = OSError('unreachable')
        with self.assertRaises(OSError):
            self.monitor.tick(self.config)
        m.subprocess.run.assert_not_called()

    def test_exited_comfy_client_can_release_gpu_after_timeout(self):
        m.save_state({'instance': m.instance(self.info), 'last_activity': 100,
                      'client': {'pid': 123, 'start': 'old-start'}})
        m.start_service.comfy_queue.side_effect = OSError('unreachable')
        with patch.object(m, 'process_start', return_value=None):
            self.monitor.tick(self.config)
        m.subprocess.run.assert_called_once()

    def test_live_comfy_client_with_unreachable_api_cannot_be_stopped(self):
        m.save_state({'instance': m.instance(self.info), 'last_activity': 100,
                      'client': {'pid': 123, 'start': 'same-start'}})
        m.start_service.comfy_queue.side_effect = OSError('unreachable')
        with patch.object(m, 'process_start', return_value='same-start'):
            with self.assertRaises(OSError):
                self.monitor.tick(self.config)
        m.subprocess.run.assert_not_called()

    def test_failed_stop_retains_state_for_retry(self):
        m.subprocess.run.side_effect = subprocess.TimeoutExpired('docker', 65)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.monitor.tick(self.config)
        self.assertTrue(m.STATE.exists())

    def test_disabled_config_leaves_service_untouched(self):
        self.assertFalse(self.monitor.tick({}))
        m.subprocess.run.assert_not_called()

    def test_busy_activity_lock_prevents_stop_and_resets_clock(self):
        with patch.object(m, 'service_activity', side_effect=RuntimeError('busy')):
            with self.assertRaises(RuntimeError):
                self.monitor.tick(self.config)
        self.assertEqual(self.monitor.last_busy, 1000)
        m.subprocess.run.assert_not_called()


@unittest.skipUnless(sys.platform == 'linux', 'Requires Linux flock shared request leases')
class LeaseTests(unittest.TestCase):
    def test_entire_job_holds_shared_lock_and_cancellation_resets_timer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = {'id': 'test', 'started_at': 'start', 'status': 'running'}
            with patch.object(m, 'SERVICE', root), patch.object(m, 'STATE', root / 'auto-state.json'), \
                    patch.object(activity, 'LOCK_PATH', root / 'activity.lock'), \
                    patch.object(m, 'require_local_docker'), patch.object(m, 'start_monitor'), \
                    patch.object(m, 'container_info', return_value=info), \
                    patch.object(m.start_service, 'comfy_queue', return_value={'queue_running': [], 'queue_pending': []}), \
                    patch.object(m.start_service, 'start_locked') as start:
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    with m.managed_service({'auto_service': {'enabled': True}}):
                        with self.assertRaises(RuntimeError):
                            with activity.service_activity(exclusive=True):
                                pass
                        with activity.service_activity():
                            pass  # The inference worker can join its node's shared lease.
                        raise RuntimeError('cancelled')
                start.assert_not_called()
                state = json.loads(m.STATE.read_text())
                self.assertEqual(state['instance'], m.instance(info))
                self.assertGreater(state['last_activity'], 0)
                with activity.service_activity(exclusive=True):
                    pass  # Cancellation released the lease.

    def test_cold_start_uses_pinned_cache_and_preserves_control_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'cache').mkdir()
            (root / 'cache/model.bin').write_bytes(b'test-model')
            (root / 'image.json').write_text('{}')
            info = {'id': 'test', 'started_at': 'start', 'status': 'running'}
            def start(**kwargs):
                self.assertTrue(kwargs['cached_only'])
                kwargs['queue_check']()
                with self.assertRaises(RuntimeError):
                    with activity.service_activity():
                        pass
            with patch.object(m, 'SERVICE', root), patch.object(m, 'STATE', root / 'auto-state.json'), \
                    patch.object(activity, 'LOCK_PATH', root / 'activity.lock'), \
                    patch.object(m, 'require_local_docker'), patch.object(m, 'start_monitor'), \
                    patch.object(m, 'container_info', side_effect=[None, info]), \
                    patch.object(m.start_service, 'comfy_queue', return_value={'queue_running': [[1, 'own']], 'queue_pending': []}), \
                    patch.object(m.start_service, 'start_locked', side_effect=start) as start_mock:
                with m.managed_service({'auto_service': {'enabled': True}}, 'own'):
                    pass
                start_mock.assert_called_once()


if __name__ == '__main__':
    unittest.main()
