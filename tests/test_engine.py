import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import Machine, MachineError, Conflict


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.workspace = root / 'workspace'
        self.workspace.mkdir()
        self.machine = Machine(self.workspace, root / 'state')

    def test_checkpoint_restore_and_backup(self):
        f = self.workspace / 'module.py'
        f.write_text('GOOD\n')
        initial = self.machine.checkpoint('good')['id']
        f.write_text('BROKEN\n')
        (self.workspace / 'extra.py').write_text('extraneous')
        self.assertEqual(len(self.machine.diff(initial)), 2)
        result = self.machine.restore(initial, self.machine.fingerprint(), confirm=True)
        self.assertEqual(f.read_text(), 'GOOD\n')
        self.assertFalse((self.workspace / 'extra.py').exists())
        self.assertTrue(result['backup'])

    def test_confirmation_required(self):
        cid = self.machine.checkpoint()['id']
        with self.assertRaises(MachineError):
            self.machine.restore(cid, self.machine.fingerprint(), False)

    def test_conflict_detection(self):
        (self.workspace / 'a.txt').write_text('before')
        cid = self.machine.checkpoint()['id']
        fingerprint = self.machine.fingerprint()
        (self.workspace / 'a.txt').write_text('surprise')
        with self.assertRaises(Conflict):
            self.machine.restore(cid, fingerprint, True)

    def test_symlink_does_not_escape(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'private').write_text('secret')
        (self.workspace / 'escape').symlink_to(outside, target_is_directory=True)
        cid = self.machine.checkpoint()['id']
        self.assertEqual(self.machine.diff(cid), [])
        self.assertEqual((outside / 'private').read_text(), 'secret')

    def test_large_files_refused(self):
        (self.workspace / 'huge.bin').write_bytes(b'a' * (8 * 1024 * 1024 + 1))
        with self.assertRaises(MachineError):
            self.machine.checkpoint()

    def test_notes(self):
        self.machine.note('Prefer tests', 'session1')
        self.assertEqual(self.machine.recent_notes('session1'), ['Prefer tests'])
        self.assertEqual(self.machine.recent_notes('session2'), [])

    def test_docker_not_available_fail_closed(self):
        self.machine.docker_ready = lambda: (False, 'No daemon')
        r = self.machine.run('touch /tmp/SHOULD_NEVER_EXIST')
        self.assertIn('BLOCKED', r)
        self.assertIn('No daemon', r)

    def test_objects_corruption_refused(self):
        f = self.workspace / 'a.txt'
        f.write_text('good')
        cid = self.machine.checkpoint()['id']
        _, files = self.machine._snapshot(cid)
        (self.machine.objects / files['a.txt']).write_text('bad')
        with self.assertRaises(MachineError):
            self.machine.restore(cid, self.machine.fingerprint(), True)

    def test_diff_preview(self):
        f = self.workspace / 'src.txt'
        f.write_text('hello\n')
        cid = self.machine.checkpoint()['id']
        f.write_text('changed\n')
        self.assertIn('-hello', self.machine.preview_text(cid, 'src.txt'))


if __name__ == '__main__':
    unittest.main()