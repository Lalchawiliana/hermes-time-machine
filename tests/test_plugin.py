import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_plugin():
    spec = importlib.util.spec_from_file_location('hermes_tm_test', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeContext:
    def __init__(self):
        self.tools = {}
        self.hooks = {}
        self.middleware = {}

    def register_tool(self, **kwargs):
        self.tools[kwargs['name']] = kwargs

    def register_hook(self, name, cb):
        self.hooks[name] = cb

    def register_middleware(self, name, cb):
        self.middleware[name] = cb


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.plugin = load_plugin()

    def test_declared_registration(self):
        ctx = FakeContext()
        self.plugin.register(ctx)
        self.assertEqual(set(ctx.tools), {'time_machine_checkpoint', 'time_machine_status', 'time_machine_note', 'time_machine_restore'})
        self.assertEqual(set(ctx.hooks), {'pre_llm_call'})
        self.assertEqual(set(ctx.middleware), {'tool_execution'})
        for name, tool in ctx.tools.items():
            self.assertEqual(tool['schema']['name'], name)

    def test_terminal_missing_config_does_not_fall_through(self):
        ctx = FakeContext()
        self.plugin.register(ctx)
        calls = []
        with patch.dict('os.environ', {'HERMES_TIMEMACHINE_WORKSPACE': ''}):
            result = ctx.middleware['tool_execution'](tool_name='terminal', args={'command':'touch /tmp/never'},
                    next_call=lambda a: calls.append(a))
        self.assertIn('TIME MACHINE BLOCKED', result)
        self.assertEqual(calls, [])

    def test_other_tool_passes_through(self):
        ctx = FakeContext()
        self.plugin.register(ctx)
        result = ctx.middleware['tool_execution'](tool_name='calculator', args={'x':2}, next_call=lambda a: a['x']*4)
        self.assertEqual(result, 8)


if __name__ == '__main__':
    unittest.main()