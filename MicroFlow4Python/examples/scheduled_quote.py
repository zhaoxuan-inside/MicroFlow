"""Explicit memory protocol demonstration; run from an installed MicroFlow package."""
import asyncio
import json
from pathlib import Path
from microflow import ScheduledRuntime, discover
from microflow.compiler import compile_release
from microflow.coordinator import Coordinator
from microflow.persistence import StorageBinding
from microflow.scheduling import ExecutionCommands
from microflow.testing import MemoryStateStore
from microflow.values import digest, load_json, thaw

HERE = Path(__file__).resolve().parent


async def main():
    project = load_json((HERE / 'quote.flow.json').read_text(encoding='utf-8'))
    release = compile_release(discover([HERE / 'quote.py']), project['flows'],
        defaults={'durability': 'ephemeral', 'recovery': {'enabled': False}})
    store = MemoryStateStore()
    coordinator = Coordinator(store)
    binding = StorageBinding('memory-test', 'runtime-state', 'example',
                             store.load_recovery_view().binding_revision, digest({}))
    commands = ExecutionCommands(coordinator, release, binding=binding, protocol_test=True)
    try:
        async with ScheduledRuntime(commands, workers=2) as runtime:
            accepted = await runtime.submit('quote', load_json((HERE / 'quote.input.json').read_text(encoding='utf-8')),
                                            request_id='scheduled-quote-example')
            result = await runtime.wait(accepted['execution_id'], timeout=5)
            print(json.dumps({'protocol': 'microflow-scheduled-example-v1', 'protocol_test': True,
                'durability': accepted['durability'], 'output': thaw(result['output'])}, sort_keys=True))
    finally:
        coordinator.close()


if __name__ == '__main__':
    asyncio.run(main())
