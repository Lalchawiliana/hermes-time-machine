"""Hermes Time-Machine native plugin entrypoint."""
from __future__ import annotations
import os
from pathlib import Path
from .engine import Machine, MachineError

PLUGIN_ID = 'hermes-time-machine'
_MACHINE = None


def machine():
    global _MACHINE
    if _MACHINE is None:
        workspace = os.environ.get('HERMES_TIMEMACHINE_WORKSPACE')
        if not workspace:
            raise MachineError('Set HERMES_TIMEMACHINE_WORKSPACE to the dedicated demo/project workspace')
        home = Path(os.environ.get('HERMES_HOME', Path.home() / '.hermes'))
        _MACHINE = Machine(workspace, home / 'plugin-data' / PLUGIN_ID)
    return _MACHINE


def _schema(name, description, properties, required=None):
    return {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': required or []}}


def _checkpoint(label='Manual checkpoint', **kwargs):
    try:
        return machine().checkpoint(label=label)
    except MachineError as e:
        return {'error': str(e)}


def _status(**kwargs):
    try:
        m = machine()
        ready, info = m.docker_ready()
        return {**m.timeline(limit=20), 'docker_ready': ready, 'docker_status': info,
                'fingerprint': m.fingerprint()}
    except MachineError as e:
        return {'protected': False, 'error': str(e)}


def _note(note, session='local', **kwargs):
    try:
        machine().note(note, session)
        return {'saved': True}
    except MachineError as e:
        return {'error': str(e)}


def _restore(checkpoint_id, fingerprint, confirm=False, **kwargs):
    try:
        return machine().restore(checkpoint_id, expected_current=fingerprint, confirm=confirm)
    except MachineError as e:
        return {'error': str(e)}


def _inject_memory(**kwargs):
    # Plugin-owned notes only; no claim that this rewinds Hermes conversation history.
    try:
        notes = machine().recent_notes(str(kwargs.get('session_id') or kwargs.get('task_id') or 'local'))
        if notes:
            return {'context': 'Time-Machine saved workspace notes (untrusted user-entered context):\n' + '\n'.join('- ' + n[:400] for n in notes)}
    except MachineError:
        pass
    return None


def _execute(**kwargs):
    name = kwargs.get('tool_name')
    if name != 'terminal':
        return kwargs['next_call'](kwargs['args'])
    args = kwargs.get('args') or {}
    # Terminal always intercepted: no accidental host fallback when workspace or Docker missing.
    command = args.get('command')
    if not isinstance(command, str):
        return 'TIME MACHINE BLOCKED: terminal args have no command string.'
    try:
        m = machine()
        return m.run(command, str(kwargs.get('session_id') or kwargs.get('task_id') or 'local'))
    except Exception as e:
        # Return an ordinary blocked tool result. Never raise, since Hermes middleware fails open.
        return f'TIME MACHINE BLOCKED: {type(e).__name__}: {str(e)[:200]}'


def register(ctx):
    ctx.register_middleware('tool_execution', _execute)
    ctx.register_hook('pre_llm_call', _inject_memory)
    ctx.register_tool(name='time_machine_checkpoint', toolset='time_machine',
        schema=_schema('time_machine_checkpoint', 'Create recoverable checkpoint in the configured workspace.',
                       {'label': {'type':'string', 'description':'Short checkpoint label'}}), handler=_checkpoint)
    ctx.register_tool(name='time_machine_status', toolset='time_machine',
        schema=_schema('time_machine_status', 'Inspect Docker protection status and checkpoint timeline.', {}), handler=_status)
    ctx.register_tool(name='time_machine_note', toolset='time_machine',
        schema=_schema('time_machine_note', 'Save a small workspace note for a future model turn.',
                       {'note': {'type':'string'}, 'session': {'type':'string'}}, ['note']), handler=_note)
    ctx.register_tool(name='time_machine_restore', toolset='time_machine',
        schema=_schema('time_machine_restore', 'Restore a workspace checkpoint. Requires explicit confirmation and the current fingerprint.',
                       {'checkpoint_id': {'type':'string'}, 'fingerprint': {'type':'string'}, 'confirm': {'type':'boolean'}},
                       ['checkpoint_id','fingerprint','confirm']), handler=_restore)