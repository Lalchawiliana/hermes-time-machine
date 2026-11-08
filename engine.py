"""Local content-addressed checkpoints, Docker execution, and transactional restore.

No dependency on Hermes internals: the engine is independently testable.
"""
from __future__ import annotations

import difflib
from contextlib import contextmanager
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import threading
import time
import uuid
from pathlib import Path

EXCLUDED = {'.git', '.hermes', 'node_modules', '.venv', '__pycache__', '.next'}
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
_LOCK = threading.RLock()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> float:
    return time.time()


class MachineError(Exception):
    pass


class Conflict(MachineError):
    pass


class Machine:
    def __init__(self, workspace: str | Path, store: str | Path):
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise MachineError('workspace must be a directory')
        self.store = Path(store).expanduser().resolve()
        if self.store == self.workspace or self.workspace in self.store.parents:
            raise MachineError('state directory must not be inside the workspace')
        self.store.mkdir(parents=True, exist_ok=True)
        self.objects = self.store / 'objects'
        self.objects.mkdir(exist_ok=True)
        self.db = self.store / 'timeline.sqlite3'
        with self._connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS checkpoints (
                  id TEXT PRIMARY KEY, created REAL NOT NULL,
                  label TEXT NOT NULL, session TEXT NOT NULL,
                  files_json TEXT NOT NULL, parent TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                  id TEXT PRIMARY KEY, created REAL NOT NULL,
                  session TEXT NOT NULL, checkpoint TEXT,
                  tool TEXT NOT NULL, status TEXT NOT NULL,
                  elapsed_ms INTEGER NOT NULL, detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notes (
                  id TEXT PRIMARY KEY, created REAL NOT NULL,
                  session TEXT NOT NULL, note TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ckpt_created ON checkpoints(created);
                CREATE INDEX IF NOT EXISTS idx_events_created ON events(created);
            ''')

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _scan(self, persist=False):
        files = {}
        total = 0
        for base, dirs, names in os.walk(self.workspace, topdown=True, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not (Path(base) / d).is_symlink())
            for name in sorted(names):
                path = Path(base) / name
                rel = path.relative_to(self.workspace).as_posix()
                try:
                    meta = path.lstat()
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(meta.st_mode):
                    continue  # never follow symlinks or snapshot special devices
                if meta.st_size > MAX_FILE:
                    raise MachineError(f'file too large to protect: {rel}')
                total += meta.st_size
                if total > MAX_TOTAL:
                    raise MachineError('workspace exceeds protection limit (128 MiB)')
                # O_NOFOLLOW closes the file symlink race on POSIX
                flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                try:
                    fd = os.open(path, flags)
                    with os.fdopen(fd, 'rb') as f:
                        data = f.read(MAX_FILE + 1)
                except (OSError, FileNotFoundError) as e:
                    raise MachineError(f'cannot safely snapshot {rel}: {e}') from e
                if len(data) > MAX_FILE:
                    raise MachineError(f'file changed while snapshotting: {rel}')
                digest = _sha(data)
                files[rel] = digest
                if persist:
                    dest = self.objects / digest
                    if not dest.exists():
                        temp = self.objects / ('.' + uuid.uuid4().hex)
                        temp.write_bytes(data)
                        os.replace(temp, dest)
        return files

    def checkpoint(self, label='Manual checkpoint', session='local'):
        with _LOCK:
            files = self._scan(persist=True)
            cid = uuid.uuid4().hex
            with self._connect() as conn:
                row = conn.execute('SELECT id FROM checkpoints ORDER BY created DESC, rowid DESC LIMIT 1').fetchone()
                conn.execute('INSERT INTO checkpoints VALUES (?,?,?,?,?,?)',
                             (cid, _now(), str(label)[:160], str(session)[:160], json.dumps(files, sort_keys=True), row['id'] if row else None))
            return {'id': cid, 'files': len(files), 'label': label}

    def _snapshot(self, cid):
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM checkpoints WHERE id=?', (cid,)).fetchone()
        if not row:
            raise MachineError('checkpoint not found')
        return dict(row), json.loads(row['files_json'])

    def latest(self):
        with self._connect() as conn:
            row = conn.execute('SELECT id FROM checkpoints ORDER BY created DESC, rowid DESC LIMIT 1').fetchone()
        return row['id'] if row else None

    def timeline(self, limit=100):
        with self._connect() as conn:
            points = [dict(row) for row in conn.execute('SELECT id,created,label,session,parent FROM checkpoints ORDER BY created DESC,rowid DESC LIMIT ?', (min(int(limit), 250),))]
            events = [dict(row) for row in conn.execute('SELECT * FROM events ORDER BY created DESC,rowid DESC LIMIT ?', (min(int(limit), 250),))]
        return {'workspace': str(self.workspace), 'checkpoints': points, 'events': events,
                'protected': True, 'latest': points[0]['id'] if points else None}

    def diff(self, cid):
        _, desired = self._snapshot(cid)
        current = self._scan()
        changes = []
        for rel in sorted(desired.keys() | current.keys()):
            before, after = desired.get(rel), current.get(rel)
            if before != after:
                changes.append({'path': rel, 'status': 'added' if before is None else 'deleted' if after is None else 'modified',
                                'checkpoint_sha': before, 'current_sha': after})
        return changes

    def preview_text(self, cid, rel):
        _, desired = self._snapshot(cid)
        if rel not in desired and rel not in self._scan():
            raise MachineError('file not found')
        old = (self.objects / desired[rel]).read_bytes() if rel in desired else b''
        p = self._safe_path(rel)
        new = p.read_bytes() if p.is_file() else b''
        try:
            old_text, new_text = old.decode('utf-8'), new.decode('utf-8')
        except UnicodeDecodeError:
            return '(binary file diff omitted)'
        return ''.join(list(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                         fromfile=f'checkpoint/{rel}', tofile=f'current/{rel}'))[:300])[:16000]

    def _safe_path(self, rel):
        p = Path(rel)
        if p.is_absolute() or not p.parts or any(x in ('..', '.', '') for x in p.parts):
            raise MachineError('unsafe path')
        cur = self.workspace
        for part in p.parts:
            cur = cur / part
            if cur.is_symlink():
                raise MachineError(f'symlink path refused: {rel}')
        if cur.resolve(strict=False) != self.workspace and self.workspace not in cur.resolve(strict=False).parents:
            raise MachineError('path escapes workspace')
        return cur

    def restore(self, cid, expected_current=None, confirm=False):
        if not confirm:
            raise MachineError('restore requires explicit confirmation')
        with _LOCK:
            _, desired = self._snapshot(cid)
            current = self._scan()
            if expected_current is None:
                raise Conflict('current workspace fingerprint is required')
            actual_fingerprint = _sha(json.dumps(current, sort_keys=True).encode())
            if expected_current != actual_fingerprint:
                raise Conflict('workspace changed since preview; refresh and retry')
            for rel in desired.keys() | current.keys():
                self._safe_path(rel)
            # validate all objects before changing any files
            for rel, digest in desired.items():
                obj = self.objects / digest
                if not obj.is_file() or _sha(obj.read_bytes()) != digest:
                    raise MachineError(f'corrupt/missing checkpoint object: {rel}')
            safety = self.checkpoint(label=f'Automatic pre-restore backup for {cid[:8]}')
            # apply deletes and rewrites, never touching excluded directories/symlinks
            for rel in sorted(current.keys() - desired.keys()):
                self._safe_path(rel).unlink()
            for rel, digest in sorted(desired.items()):
                target = self._safe_path(rel)
                if current.get(rel) == digest:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.parent / ('.tm-' + uuid.uuid4().hex)
                shutil.copyfile(self.objects / digest, tmp)
                os.replace(tmp, target)
            restored = self.checkpoint(label=f'Restored {cid[:8]}')
            return {'restored': cid, 'backup': safety['id'], 'new_checkpoint': restored['id']}

    def fingerprint(self):
        with _LOCK:
            return _sha(json.dumps(self._scan(), sort_keys=True).encode())

    def event(self, tool, status, session='local', checkpoint=None, elapsed_ms=0, detail=''):
        with self._connect() as conn:
            conn.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?)',
                         (uuid.uuid4().hex, _now(), str(session)[:160], checkpoint,
                          str(tool)[:80], str(status)[:40], int(elapsed_ms), str(detail)[:300]))

    def note(self, text, session='local'):
        with self._connect() as conn:
            conn.execute('INSERT INTO notes VALUES (?,?,?,?)', (uuid.uuid4().hex, _now(), str(session)[:160], str(text)[:2000]))

    def recent_notes(self, session='local', limit=4):
        with self._connect() as conn:
            return [r['note'] for r in conn.execute('SELECT note FROM notes WHERE session=? ORDER BY created DESC LIMIT ?', (str(session)[:160], limit))]

    def docker_ready(self):
        if shutil.which('docker') is None:
            return False, 'Docker executable not installed'
        try:
            proc = subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'], capture_output=True, timeout=5, text=True)
            return (proc.returncode == 0, 'Docker running' if proc.returncode == 0 else 'Docker daemon inaccessible')
        except (OSError, subprocess.TimeoutExpired):
            return False, 'Docker daemon inaccessible'

    def run(self, command, session='local', image='python:3.12-alpine', timeout=45):
        """Run command ONLY inside Docker; never fall back to host execution."""
        if not isinstance(command, str) or not command.strip() or len(command) > 20000:
            raise MachineError('invalid terminal command')
        ready, reason = self.docker_ready()
        if not ready:
            self.event('terminal', 'blocked', session, detail=reason)
            return f'TIME MACHINE BLOCKED: {reason}. No host command was run.'
        started = time.monotonic()
        with _LOCK:
            before = self.checkpoint('Before terminal execution', session)
            # fixed argv; shell command evaluated only inside the container.
            container_name = 'htm-' + uuid.uuid4().hex[:20]
            argv = ['docker', 'run', '--rm', '--name', container_name, '--network', 'none', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges', '--read-only', '--tmpfs', '/tmp:rw,nosuid,size=64m', '--pids-limit', '128',
                    '--memory', '512m', '--cpus', '1', '--user', f'{os.getuid()}:{os.getgid()}' if hasattr(os, 'getuid') else '65534:65534',
                    '--mount', f'type=bind,src={self.workspace},dst=/workspace',
                    '--workdir', '/workspace', image, '/bin/sh', '-lc', command]
            try:
                proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
                output = ((proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else ''))[:20000]
                status = 'ok' if proc.returncode == 0 else 'failed'
                output = f'[Time-Machine Docker exit={proc.returncode}]\n{output}'
            except subprocess.TimeoutExpired:
                # Killing the docker CLIENT may not stop the container. Force-remove it.
                try:
                    subprocess.run(['docker', 'rm', '-f', container_name], capture_output=True, timeout=8)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                status, output = 'timeout', f'[Time-Machine Docker timed out after {timeout}s]'
            except OSError as e:
                status, output = 'blocked', f'TIME MACHINE BLOCKED: Docker execution failed: {type(e).__name__}'
            after = self.checkpoint('After terminal execution', session)
            self.event('terminal', status, session, after['id'], int((time.monotonic()-started)*1000),
                       f'before={before["id"][:8]} after={after["id"][:8]}')
            return output