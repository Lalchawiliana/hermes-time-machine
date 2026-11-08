"""Authenticated Hermes plugin-scoped backend. Host mounts at /api/plugins/hermes-time-machine."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


_INSTANCE = None


def _machine():
    global _INSTANCE
    if _INSTANCE is None:
        import importlib.util
        from pathlib import Path
        import os
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('time_machine_engine_backend', root / 'engine.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        workspace = os.environ.get('HERMES_TIMEMACHINE_WORKSPACE')
        if not workspace:
            raise ValueError('Set HERMES_TIMEMACHINE_WORKSPACE before starting Hermes')
        home = Path(os.environ.get('HERMES_HOME', Path.home() / '.hermes'))
        _INSTANCE = mod.Machine(workspace, home / 'plugin-data' / 'hermes-time-machine')
    return _INSTANCE


class RestoreRequest(BaseModel):
    checkpoint_id: str
    fingerprint: str
    confirm: bool = False


class NoteRequest(BaseModel):
    text: str
    session: str = 'local'


@router.get('/status')
def status():
    try:
        m = _machine()
        ready, reason = m.docker_ready()
        return {**m.timeline(), 'docker_ready': ready, 'docker_status': reason,
                'fingerprint': m.fingerprint()}
    except Exception as e:
        return {'protected': False, 'error': str(e), 'checkpoints': [], 'events': []}


@router.get('/diff/{checkpoint_id}')
def diff(checkpoint_id: str):
    try:
        m = _machine()
        return {'changes': m.diff(checkpoint_id), 'fingerprint': m.fingerprint()}
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@router.post('/restore')
def restore(body: RestoreRequest):
    if not body.confirm:
        raise HTTPException(400, 'explicit confirmation required')
    try:
        return _machine().restore(body.checkpoint_id, body.fingerprint, True)
    except Exception as e:
        raise HTTPException(409, str(e)) from e


@router.post('/checkpoint')
def checkpoint():
    try:
        return _machine().checkpoint('Manual Desktop checkpoint')
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@router.post('/note')
def note(body: NoteRequest):
    if len(body.text) > 2000:
        raise HTTPException(400, 'note exceeds 2000 characters')
    try:
        _machine().note(body.text, body.session)
        return {'saved': True}
    except Exception as e:
        raise HTTPException(400, str(e)) from e