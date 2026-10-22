import asyncio
from dataclasses import asdict
import threading
import unittest
from microflow.compiler import compile_release
from microflow.coordinator import Coordinator
from microflow.errors import ContractError, PersistenceError
from microflow.persistence import StorageBinding
from microflow.registry import Registry
from microflow.runtime import LocalRuntime
from microflow.scheduling import ExecutionCommands
from microflow.testing import MemoryStateStore
from microflow.values import digest
from microflow.worker import ScheduledRuntime
from tests.test_compiler import INTEGER_MAP, EPHEMERAL, flow, method
from tests.test_runtime import throwing, fallback, rejecting, broken_collector, coroutine
from tests.test_policy import DURABLE


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    def make(self, main=method, *, definition=None, store=None, defaults=None, clock=None, **handlers):
        registered = Registry()
        registered.register_schema('ints', INTEGER_MAP)
        registered.register_operator(name='increment', version='1', method=main,
            input_schema='ints', output_schema='ints', **handlers)
        release = compile_release(registered, [definition or flow()], defaults=defaults or EPHEMERAL,
                                  provider_capabilities=DURABLE)
        store = store or MemoryStateStore()
        binding = StorageBinding('test', 'runtime-state', 'worker-test', store.load_recovery_view().binding_revision, digest({}))
        return ExecutionCommands(Coordinator(store), release, binding=binding, protocol_test=True, clock=clock), store

    async def test_static_dag_matches_local_result_and_stable_identity(self):
        commands, _ = self.make()
        expected = await LocalRuntime(commands.release).run_async('example', {'n': 1})
        runtime = ScheduledRuntime(commands, workers=1)
        async with runtime:
            accepted = await runtime.submit('example', {'n': 1}, request_id='accept')
            self.assertEqual(accepted['status'], 'ACCEPTED')
            result = await runtime.wait(accepted['execution_id'], timeout=2)
            self.assertEqual(result['output']['data'], expected.output['data'])
            self.assertEqual(result['status'], 'SUCCEEDED')
            self.assertEqual((await runtime.submit('example', {'n': 1}, request_id='accept')), accepted)
            with self.assertRaises(TypeError):
                result['output']['data']['n'] = 0
        completed = [r for r in runtime.records if r['event'] == 'invocation_completed']
        self.assertEqual(len(completed), 2)
        self.assertEqual(completed[0]['invocationId'], result['nodes']['first']['output']['meta']['invocationId'])
        self.assertEqual(completed[0]['parentInvocationId'], accepted['execution_id'])
        await runtime.close()
        with self.assertRaisesRegex(ContractError, 'RUNTIME_CLOSED'):
            await runtime.submit('example', {'n': 1}, request_id='closed')

    async def test_sync_work_does_not_block_event_loop_or_waiter_cancellation(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def blocking(input, output, context, metrix, debug, log):
            calls.append(input['n'])
            entered.set()
            release.wait(3)
            output.set('n', input['n'] + 1)
            return True
        commands, _ = self.make(blocking)
        async with ScheduledRuntime(commands, workers=1) as runtime:
            accepted = await runtime.submit('example', {'n': 1}, request_id='accept')
            execution = accepted['execution_id']
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                waiting = asyncio.create_task(runtime.wait(execution))
                await asyncio.sleep(.01)
                waiting.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await waiting
                with self.assertRaises(TimeoutError):
                    await runtime.wait(execution, timeout=.01)
                self.assertEqual(commands.query(execution)['nodes']['first']['status'], 'CLAIMED')
            finally:
                release.set()
            self.assertEqual((await runtime.wait(execution, timeout=2))['status'], 'SUCCEEDED')
        self.assertEqual(calls, [1, 2])

    async def test_explicit_cancel_cooperates_without_cancelling_live_thread(self):
        entered, release = threading.Event(), threading.Event()
        def blocking(input, output, context, metrix, debug, log):
            entered.set()
            release.wait(3)
            output.set('n', input['n'] + 1)
            return True
        commands, _ = self.make(blocking)
        async with ScheduledRuntime(commands, workers=1) as runtime:
            execution = (await runtime.submit('example', {'n': 1}, request_id='accept'))['execution_id']
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                self.assertEqual((await runtime.cancel(execution, request_id='cancel'))['status'], 'STOPPING')
                await asyncio.sleep(.03)
                self.assertEqual(commands.query(execution)['status'], 'STOPPING')
            finally:
                release.set()
            state = await runtime.wait(execution, timeout=2)
            self.assertEqual(state['status'], 'CANCELLED')
            self.assertEqual(state['nodes']['second']['status'], 'SKIPPED')

    async def test_coroutine_work_and_wait_do_not_consume_business_threads(self):
        commands, _ = self.make(coroutine)
        async with ScheduledRuntime(commands, workers=1) as runtime:
            state = await runtime.run('example', {'n': 1}, request_id='async', timeout=2)
        self.assertEqual(state['output']['data']['n'], 5)

    async def test_parallel_ready_nodes_respect_worker_capacity(self):
        active, maximum = 0, 0
        both = asyncio.Event()
        release = asyncio.Event()
        async def parallel(input, output, context, metrix, debug, log):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                both.set()
            await release.wait()
            output.set('n', input['n'] + 1)
            active -= 1
            return True
        definition = flow()
        definition['nodes']['peer'] = {'operator': 'increment@1', 'inputs': {'n': {'from': 'flow.input.n'}}}
        commands, _ = self.make(parallel, definition=definition)
        async with ScheduledRuntime(commands, workers=2) as runtime:
            accepted = await runtime.submit('example', {'n': 1}, request_id='parallel')
            try:
                await asyncio.wait_for(both.wait(), 1)
                self.assertEqual(maximum, 2)
            finally:
                release.set()
            self.assertEqual((await runtime.wait(accepted['execution_id'], timeout=2))['status'], 'SUCCEEDED')
        self.assertLessEqual(maximum, 2)

    async def test_failure_is_committed_before_slow_optional_collectors(self):
        collecting, release = asyncio.Event(), asyncio.Event()
        async def collector(input, output, context, metrix, debug, log):
            observed = context.resource('commands').query(context.options['flowInstanceId'])
            self.assertEqual(observed['status'], 'FAILED')
            collecting.set()
            await release.wait()
            return True
        commands, _ = self.make(throwing, log=collector)
        async with ScheduledRuntime(commands, resources={'commands': commands}) as runtime:
            execution = (await runtime.submit('example', {'n': 1}, request_id='fail'))['execution_id']
            try:
                await asyncio.wait_for(collecting.wait(), 1)
                result = await runtime.wait(execution, timeout=.2)
                self.assertEqual(result['output']['error']['code'], 'UNHANDLED_OPERATOR_EXCEPTION')
                self.assertEqual(result['nodes']['second']['status'], 'SKIPPED')
                self.assertNotIn('private password', str(result))
            finally:
                release.set()

    async def test_fallback_and_collector_failures_preserve_business_result(self):
        commands, _ = self.make(throwing, fallback=fallback,
            fallback_capabilities={'effect': 'pure', 'idempotency_support': 'natural'}, log=broken_collector)
        async with ScheduledRuntime(commands) as runtime:
            result = await runtime.run('example', {'n': 1}, request_id='fallback', timeout=2)
        self.assertEqual(result['output']['data']['n'], 21)
        self.assertEqual(result['nodes']['first']['output']['meta']['resolution'], 'fallback')
        self.assertEqual(sum(r['event'] == 'collector_failed' for r in runtime.records), 2)

    async def test_false_never_invokes_fallback(self):
        def forbidden(input, output, context, metrix, debug, log):
            self.fail('False must not invoke fallback')
        commands, _ = self.make(rejecting, fallback=forbidden,
            fallback_capabilities={'effect': 'pure', 'idempotency_support': 'natural'})
        async with ScheduledRuntime(commands) as runtime:
            result = await runtime.run('example', {'n': 1}, request_id='rejected', timeout=2)
        self.assertEqual(result['output']['error']['code'], 'OPERATOR_REJECTED')

    async def test_failed_completion_commit_blocks_without_business_reexecution(self):
        calls = []
        def counted(input, output, context, metrix, debug, log):
            calls.append(1)
            output.set('n', input['n'] + 1)
            return True
        class FailedCompletion(MemoryStateStore):
            def commit(self, batch, *args):
                if any(k.startswith('execution/') and r['nodes']['first']['status'] == 'SUCCEEDED'
                       for k, r in batch.puts.items()):
                    raise OSError('state unavailable')
                return super().commit(batch, *args)
        commands, _ = self.make(counted, store=FailedCompletion())
        async with ScheduledRuntime(commands) as runtime:
            execution = (await runtime.submit('example', {'n': 1}, request_id='accept'))['execution_id']
            with self.assertRaisesRegex(PersistenceError, 'EXECUTION_BLOCKED'):
                await runtime.wait(execution, timeout=2)
        self.assertEqual(calls, [1])
        self.assertEqual(runtime.blocked[execution], 'COMMIT_FAILED')
        with self.assertRaises(TypeError):
            runtime.blocked[execution] = 'changed'
        self.assertEqual(commands.query(execution)['nodes']['first']['status'], 'CLAIMED')
        self.assertEqual(commands.ready(execution), ())

    async def test_admission_survives_caller_disconnection(self):
        entered, release = threading.Event(), threading.Event()
        class SlowAdmission(MemoryStateStore):
            def commit(self, batch, expected_revision, request_id, owner):
                if request_id == 'admit':
                    entered.set()
                    release.wait(3)
                return super().commit(batch, expected_revision, request_id, owner)
        commands, store = self.make(store=SlowAdmission())
        async with ScheduledRuntime(commands) as runtime:
            caller = asyncio.create_task(runtime.submit('example', {'n': 1}, request_id='admit'))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                caller.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await caller
            finally:
                release.set()
            execution = digest({'binding': asdict(commands.binding), 'request_id': 'admit'})
            for _ in range(100):
                if 'execution/' + execution in store.load_recovery_view().records:
                    break
                await asyncio.sleep(.01)
            self.assertEqual((await runtime.wait(execution, timeout=2))['output']['data']['n'], 3)

    async def test_preexisting_claim_requires_recovery_and_is_not_replayed(self):
        calls = []
        def forbidden(input, output, context, metrix, debug, log):
            calls.append(1)
            return True
        commands, _ = self.make(forbidden)
        execution = commands.accept('example', {'n': 1}, request_id='accept')['execution_id']
        commands.claim(execution, 'first', worker_id='lost', request_id='claim')
        async with ScheduledRuntime(commands) as runtime:
            with self.assertRaises(PersistenceError) as caught:
                await runtime.wait(execution, timeout=2)
            self.assertEqual(caught.exception.diagnostic.details['cause_code'], 'RECOVERY_REQUIRED')
        self.assertEqual(calls, [])

    async def test_records_are_bounded_and_debug_pause_is_refused(self):
        def pause(input, output, context, metrix, debug, log):
            debug.pause()
            return True
        commands, _ = self.make(pause)
        async with ScheduledRuntime(commands, max_records=2) as runtime:
            result = await runtime.run('example', {'n': 1}, request_id='pause', timeout=2)
        self.assertEqual(result['output']['error']['code'], 'UNSAFE_PAUSE')
        self.assertLessEqual(len(runtime.records), 2)

    async def test_mixed_dispatch_policies_keep_wait_semantics(self):
        definition = flow()
        definition['nodes']['second']['policy'] = {'execution_mode': 'async'}
        commands, _ = self.make(definition=definition, defaults={'durability': 'durable'})
        async with ScheduledRuntime(commands, workers=1) as runtime:
            state = await runtime.run('example', {'n': 1}, request_id='mixed', timeout=2)
        self.assertEqual(state['output']['data']['n'], 3)
        modes = [r['executionMode'] for r in runtime.records if r['event'] == 'attempt_started']
        self.assertEqual(modes, ['sync', 'async'])

    async def test_close_drains_accepted_work(self):
        commands, _ = self.make(coroutine)
        runtime = ScheduledRuntime(commands, workers=1)
        execution = (await runtime.submit('example', {'n': 1}, request_id='accept'))['execution_id']
        await runtime.close()
        self.assertEqual(commands.query(execution)['status'], 'SUCCEEDED')

    async def test_terminal_view_does_not_replace_completion_acknowledgment(self):
        entered, release = threading.Event(), threading.Event()
        class SlowAcknowledgment(MemoryStateStore):
            def commit(self, batch, *args):
                receipt = super().commit(batch, *args)
                if any(k.startswith('execution/') and r['status'] == 'SUCCEEDED' for k, r in batch.puts.items()):
                    entered.set()
                    release.wait(3)
                return receipt
        definition = flow()
        del definition['nodes']['second']
        definition['outputs']['n']['from'] = 'nodes.first.output.data.n'
        commands, _ = self.make(store=SlowAcknowledgment(), definition=definition)
        async with ScheduledRuntime(commands) as runtime:
            execution = (await runtime.submit('example', {'n': 1}, request_id='accept'))['execution_id']
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                self.assertEqual(commands.query(execution)['status'], 'SUCCEEDED')
                with self.assertRaises(TimeoutError):
                    await runtime.wait(execution, timeout=.02)
            finally:
                release.set()
            self.assertEqual((await runtime.wait(execution, timeout=2))['status'], 'SUCCEEDED')

    async def test_unhandled_exception_is_not_replaced_by_soft_timeout(self):
        now = [100.0]
        async def slow_failure(input, output, context, metrix, debug, log):
            await asyncio.sleep(.01)
            now[0] += 2
            raise RuntimeError('private failure')
        definition = flow()
        definition['nodes']['first']['policy'] = {'timeout': {'attempt': '1s'}}
        commands, _ = self.make(slow_failure, definition=definition, clock=lambda: now[0])
        async with ScheduledRuntime(commands, poll_interval=.1) as runtime:
            state = await runtime.run('example', {'n': 1}, request_id='failure', timeout=2)
        self.assertEqual(state['output']['error']['code'], 'UNHANDLED_OPERATOR_EXCEPTION')

    async def test_invalid_wait_budget_does_not_accept_business(self):
        commands, store = self.make()
        async with ScheduledRuntime(commands) as runtime:
            for timeout in (-1, True, float('nan')):
                with self.subTest(timeout=timeout), self.assertRaisesRegex(ContractError, 'INVALID_WAIT_TIMEOUT'):
                    await runtime.run('example', {'n': 1}, request_id='invalid', timeout=timeout)
        self.assertEqual(dict(store.load_recovery_view().records), {})

    async def test_runtime_cannot_be_shared_across_event_loops(self):
        commands, _ = self.make()
        async with ScheduledRuntime(commands) as runtime:
            def other_loop():
                return asyncio.run(runtime.wait('unknown'))
            with self.assertRaisesRegex(ContractError, 'RUNTIME_LOOP_MISMATCH'):
                await asyncio.to_thread(other_loop)

    async def until(self, predicate):
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(.005)
        self.fail('Expected state transition was not observed')

    async def test_queue_timeout_while_pool_full_never_starts_queued_node(self):
        now = [100.0]
        entered, release = threading.Event(), threading.Event()
        calls = []
        def blocking(input, output, context, metrix, debug, log):
            calls.append(context.options['invocationId'])
            entered.set()
            release.wait(3)
            output.set('n', input['n'] + 1)
            return True
        definition = flow()
        definition['nodes']['peer'] = {'operator': 'increment@1', 'inputs': {'n': {'from': 'flow.input.n'}},
                                       'policy': {'timeout': {'queue': '2s'}}}
        commands, _ = self.make(blocking, definition=definition, clock=lambda: now[0])
        async with ScheduledRuntime(commands, workers=1) as runtime:
            execution = (await runtime.submit('example', {'n': 1}, request_id='accept'))['execution_id']
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                now[0] = 103
                await self.until(lambda: commands.query(execution)['status'] == 'STOPPING')
                peer = commands.query(execution)['nodes']['peer']
                self.assertEqual(peer['output']['error']['code'], 'QUEUE_TIMEOUT')
                self.assertIsNone(peer['claimed_at'])
            finally:
                release.set()
            result = await runtime.wait(execution, timeout=2)
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['nodes']['first']['output']['data']['n'], 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(r['event'] == 'attempt_started' for r in runtime.records), 1)

    async def test_attempt_timer_keeps_live_thread_and_late_success(self):
        now = [100.0]
        entered, release = threading.Event(), threading.Event()
        def blocking(input, output, context, metrix, debug, log):
            entered.set()
            release.wait(3)
            output.set('n', input['n'] + 1)
            return True
        definition = flow()
        definition['nodes']['first']['policy'] = {'timeout': {'attempt': '2s'}}
        commands, _ = self.make(blocking, definition=definition, clock=lambda: now[0])
        async with ScheduledRuntime(commands, workers=1) as runtime:
            execution = (await runtime.submit('example', {'n': 1}, request_id='accept'))['execution_id']
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                now[0] = 103
                await self.until(lambda: commands.query(execution)['status'] == 'STOPPING')
                node = commands.query(execution)['nodes']['first']
                self.assertEqual(node['status'], 'CLAIMED')
                self.assertEqual(node['timeout_code'], 'ATTEMPT_TIMEOUT')
                self.assertIsNone(node['finished_at'])
                with self.assertRaises(TimeoutError):
                    await runtime.wait(execution, timeout=.02)
            finally:
                release.set()
            result = await runtime.wait(execution, timeout=2)
            self.assertEqual(result['output']['error']['code'], 'ATTEMPT_TIMEOUT')
            self.assertEqual(result['nodes']['first']['status'], 'SUCCEEDED')
            self.assertEqual(result['nodes']['first']['output']['data']['n'], 2)
            self.assertEqual(result['nodes']['second']['status'], 'SKIPPED')

    async def test_root_deadline_requests_coroutine_cooperation_without_task_cancel(self):
        now = [100.0]
        entered, release = asyncio.Event(), asyncio.Event()
        async def pending(input, output, context, metrix, debug, log):
            entered.set()
            await release.wait()
            output.set('n', input['n'] + 1)
            return True
        definition = flow()
        definition['nodes']['first']['policy'] = {'timeout': {'deadline': '2s'}}
        commands, _ = self.make(pending, definition=definition, clock=lambda: now[0])
        async with ScheduledRuntime(commands) as runtime:
            execution = (await runtime.submit('example', {'n': 1}, request_id='accept'))['execution_id']
            try:
                await asyncio.wait_for(entered.wait(), 1)
                now[0] = 103
                await self.until(lambda: commands.query(execution)['status'] == 'STOPPING')
                self.assertEqual(commands.query(execution)['stop']['code'], 'DEADLINE_EXCEEDED')
                with self.assertRaises(TimeoutError):
                    await runtime.wait(execution, timeout=.02)
            finally:
                release.set()
            result = await runtime.wait(execution, timeout=2)
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['nodes']['first']['output']['data']['n'], 2)

    async def test_fallback_cannot_begin_after_attempt_budget(self):
        now = [100.0]
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def failing(input, output, context, metrix, debug, log):
            entered.set()
            await release.wait()
            raise RuntimeError('private error')
        def forbidden(input, output, context, metrix, debug, log):
            calls.append(1)
            return True
        definition = flow()
        definition['nodes']['first']['policy'] = {'timeout': {'attempt': '2s'}}
        commands, _ = self.make(failing, definition=definition, clock=lambda: now[0], fallback=forbidden,
            fallback_capabilities={'effect': 'pure', 'idempotency_support': 'natural'})
        async with ScheduledRuntime(commands) as runtime:
            execution = (await runtime.submit('example', {'n': 1}, request_id='accept'))['execution_id']
            await asyncio.wait_for(entered.wait(), 1)
            now[0] = 103
            release.set()
            result = await runtime.wait(execution, timeout=2)
        self.assertEqual(result['output']['error']['code'], 'ATTEMPT_TIMEOUT')
        self.assertEqual(calls, [])
