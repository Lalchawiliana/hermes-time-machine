"""Real file-change demonstration; Docker agent run is separate (see README)."""
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import Machine

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    workspace = root / 'sample-project'
    workspace.mkdir()
    source = workspace / 'calculator.py'
    source.write_text('def add(a, b):\n    return a + b\n')
    machine = Machine(workspace, root / 'state')
    good = machine.checkpoint('All tests green')
    print('GOOD CHECKPOINT:', good['id'])
    source.write_text('def add(a, b):\n    return a - b\n')
    (workspace / 'README.md').write_text('accidental file')
    broken = machine.checkpoint('Broken refactor')
    print('CHANGES:', machine.diff(good['id']))
    restored = machine.restore(good['id'], machine.fingerprint(), confirm=True)
    print('RESTORED:', restored)
    assert source.read_text() == 'def add(a, b):\n    return a + b\n'
    assert not (workspace / 'README.md').exists()
    print('SUCCESS: source restored; pre-restore backup retained')