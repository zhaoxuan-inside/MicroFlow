"""Event-loop-owned static DAG execution over atomic state commands.

No lease takeover, automatic redelivery, hard thread cancellation or durable
artifact publication is implemented by this driver.
"""
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import inspect
import math
import threading
import uuid

from .errors import ContractError, PersistenceError
from .policy import EffectiveOperatorPolicy
from .runtime import LocalRuntime
from .scheduling import TERMINAL
from .values import digest, freeze, validate_value


class _WorkerRuntime(LocalRuntime):
    def __init__(self, release, resources, pool):
        super().__init__(release, resources=resources)
        self.pool = pool

    async def _call(self, method, args):
        if inspect.iscoroutinefunction(method):
            return await method(*args)
        return await asyncio.get_running_loop().run_in_executor(self.pool, method, *args)


class _BudgetCancellation(threading.Event):
    def __init__(self, commands, task):
        super().__init__()
        self._clock = commands.clock_time
        self._deadline = min(task['attempt_deadline_at'], task['deadline_at'])
        self._floor = task['claimed_at']

    def is_set(self):
        if super().is_set():
            return True
        now = self._clock()
        if now < self._floor:
            raise PersistenceError('CLOCK_REGRESSION', 'Clock is behind the claimed attempt')
        return now >= self._deadline


class ScheduledRuntime:
    """Use as an async context manager on one event loop.

    submit returns committed acceptance; run/wait await actual business completion.
    Cancelling or timing out a waiter never cancels owned work. close drains work.
    A command failure blocks that execution without replaying its business method.
    """
    def __init__(self, commands, *, workers=4, poll_interval=.01, resources=None, max_records=1000):
        if type(workers) is not int or workers < 1 or type(max_records) is not int or max_records < 1:
            raise ContractError('INVALID_RUNTIME', 'Worker and record budgets must be positive integers')
        if type(poll_interval) not in (int, float) or not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ContractError('INVALID_RUNTIME', 'Polling interval must be positive and finite')
        self.commands = commands
        self.workers, self.poll_interval = workers, poll_interval
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='microflow-business')
        self._worker = _WorkerRuntime(commands.release, resources, self._pool)
        self._records = deque(maxlen=max_records)
        self._worker_id = uuid.uuid4().hex
        self._loop = None
        self._tracked = set()
        self._jobs = {}
        self._unconfirmed = set()
        self._admissions = set()
        self._blocked = {}
        self._pump_task = None
        self._closing = False
        self._closed = False

    def _bind(self):
        loop = asyncio.get_running_loop()
        if self._closed:
            raise ContractError('RUNTIME_CLOSED', 'Runtime is closed')
        if self._loop is not None and self._loop is not loop:
            raise ContractError('RUNTIME_LOOP_MISMATCH', 'Runtime belongs to another event loop')
        self._loop = loop

    async def _command(self, method, *args, **kwargs):
        # State I/O uses the host pool, separate from business execution capacity.
        return await asyncio.to_thread(method, *args, **kwargs)

    async def _watch(self, execution_id):
        state = await self._command(self.commands.query, execution_id)
        if state['status'] not in TERMINAL:
            self._tracked.add(execution_id)
            if self._pump_task is None or self._pump_task.done():
                self._pump_task = asyncio.create_task(self._pump())
        return state

    async def submit(self, flow_id, data, *, request_id):
        self._bind()
        if self._closing:
            raise ContractError('RUNTIME_CLOSED', 'Runtime no longer accepts work')
        if len(self._admissions) >= self.commands.max_active:
            raise ContractError('EXECUTION_BACKPRESSURE', 'Pending admission budget exhausted')
        validate_value(data)
        data = freeze(data)
        async def admitting():
            accepted = await self._command(self.commands.accept, flow_id, data, request_id=request_id)
            await self._watch(accepted['execution_id'])
            return freeze(accepted)
        admission = asyncio.create_task(admitting())
        self._admissions.add(admission)
        def finished(task):
            self._admissions.discard(task)
            if not task.cancelled():
                task.exception()  # Consume failures even if the caller disconnected.
        admission.add_done_callback(finished)
        return await asyncio.shield(admission)

    async def wait(self, execution_id, *, timeout=None):
        self._bind()
        self._validate_timeout(timeout)
        async def waiting():
            while True:
                state = await self._watch(execution_id)
                if execution_id in self._blocked:
                    raise PersistenceError('EXECUTION_BLOCKED', 'Execution needs host intervention',
                                           execution_id=execution_id, cause_code=self._blocked[execution_id])
                if state['status'] in TERMINAL and not any(key[0] == execution_id for key in self._unconfirmed):
                    return state
                await asyncio.sleep(self.poll_interval)
        # wait_for cancels only this polling waiter, never the pump or business jobs.
        if timeout is None:
            return await waiting()
        return await asyncio.wait_for(waiting(), timeout)

    async def run(self, flow_id, data, *, request_id, timeout=None):
        self._validate_timeout(timeout)
        accepted = await self.submit(flow_id, data, request_id=request_id)
        return await self.wait(accepted['execution_id'], timeout=timeout)

    @staticmethod
    def _validate_timeout(timeout):
        if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0):
            raise ContractError('INVALID_WAIT_TIMEOUT', 'Wait timeout must be nonnegative and finite')

    async def cancel(self, execution_id, *, request_id):
        self._bind()
        result = await self._command(self.commands.cancel, execution_id, request_id=request_id)
        await self._watch(execution_id)
        return freeze(result)

    @property
    def records(self):
        return tuple(freeze(record) for record in self._records)

    @property
    def blocked(self):
        return freeze(dict(self._blocked))

    def _block(self, execution_id, error):
        diagnostic = getattr(error, 'diagnostic', None)
        self._blocked[execution_id] = diagnostic.error_code if diagnostic else 'WORKER_INTERRUPTED'
        self._tracked.discard(execution_id)

    async def _execute(self, task, cancel, options):
        policy = EffectiveOperatorPolicy(freeze(task['policy']['values']), task['policy']['digest'])
        state = {'cancel': cancel, 'records': self._records, 'stop': None, 'deadline': float('inf'),
                 'trace_id': options['traceId']}
        async def publish(output):
            resolution = output['meta']['resolution']
            code = output['error']['code'] if output['error'] else None
            if resolution == 'unhandled_exception' and code != 'UNHANDLED_OPERATOR_EXCEPTION':
                resolution = 'main'
            await self._command(self.commands.complete, task, status=output['meta']['status'], data=output['data'],
                                error_code=code, resolution=resolution,
                                request_id=digest({'operation': 'complete', 'task': task}))
            self._unconfirmed.discard((task['execution_id'], task['node_id'], task['attempt_epoch']))
        operator = self.commands.release.registry.operators[task['operator']]
        return await self._worker._operator(operator, task['input'], policy, state, options, task['execution_id'],
            on_result=publish, invocation_id=digest([task['execution_id'], task['node_id']]),
            attempt_id=digest([task['execution_id'], task['node_id'], task['attempt_epoch'], task['owner']]),
            can_pause=False, enforce_return_budget=False)

    async def _pump(self):
        while self._tracked or self._jobs:
            for key, (job, cancel) in list(self._jobs.items()):
                if job.done():
                    del self._jobs[key]
                    try:
                        job.result()
                    except BaseException as error:
                        self._block(key[0], error)
                    self._unconfirmed.discard(key)
            for execution_id in sorted(self._tracked):
                if execution_id in self._blocked:
                    self._tracked.discard(execution_id)
                    continue
                try:
                    state = await self._command(self.commands.query, execution_id)
                    expiry = self.commands.next_expiry(state)
                    if expiry is not None and self.commands.clock_time() >= expiry:
                        try:
                            await self._command(self.commands.expire, execution_id,
                                request_id=digest({'operation': 'expire', 'execution_id': execution_id, 'deadline': expiry}))
                        except ContractError as error:
                            if error.diagnostic.error_code != 'BUDGET_NOT_EXPIRED':
                                raise
                        state = await self._command(self.commands.query, execution_id)
                    if any(n['status'] == 'WAITING_OPERATION' for n in state['nodes'].values()):
                        pending = await self._command(self.commands.pending_operations, execution_id)
                        if any(p['status'] != 'IN_PROGRESS' for p in pending.values()):
                            try:
                                await self._command(self.commands.refresh_operations, execution_id,
                                    request_id=digest({'operation': 'refresh_operations', 'execution_id': execution_id,
                                                       'pending': pending}))
                            except ContractError as error:
                                if error.diagnostic.error_code != 'OPERATION_PENDING':
                                    raise
                            state = await self._command(self.commands.query, execution_id)
                    for key, (job, cancel) in self._jobs.items():
                        if key[0] == execution_id and state['nodes'][key[1]]['cancel_requested']:
                            cancel.set()
                    if state['status'] in TERMINAL:
                        self._tracked.discard(execution_id)
                        continue
                    for name in self.commands.release.flows[state['flow_id']].graph.order:
                        if len(self._jobs) >= self.workers:
                            break
                        if state['stop'] is not None or state['nodes'][name]['status'] != 'READY':
                            continue
                        identity = {'execution_id': execution_id, 'node_id': name, 'worker': self._worker_id,
                                    'owner': asdict(self.commands.coordinator.owner)}
                        try:
                            task = await self._command(self.commands.claim, execution_id, name,
                                worker_id=self._worker_id, request_id=digest({'operation': 'claim', **identity}))
                        except ContractError as error:
                            if error.diagnostic.error_code in ('NODE_NOT_READY', 'EXECUTION_STOPPED', 'EXECUTION_BACKPRESSURE'):
                                continue
                            raise
                        if task['status'] != 'CLAIMED':
                            continue
                        key = execution_id, name, task['attempt_epoch']
                        if key not in self._jobs:
                            cancel = _BudgetCancellation(self.commands, task)
                            self._unconfirmed.add(key)
                            self._jobs[key] = asyncio.create_task(self._execute(task, cancel, state['options'])), cancel
                    if (not any(key[0] == execution_id for key in self._jobs)
                            and any(n['status'] == 'CLAIMED' for n in state['nodes'].values())):
                        raise PersistenceError('RECOVERY_REQUIRED', 'Existing claimed work cannot be automatically redelivered')
                except Exception as error:
                    self._block(execution_id, error)
            if self._tracked or self._jobs:
                await asyncio.sleep(self.poll_interval)

    async def close(self):
        if self._closed:
            return
        self._bind()
        self._closing = True
        if self._admissions:
            await asyncio.shield(asyncio.gather(*self._admissions, return_exceptions=True))
        if self._pump_task is not None:
            await asyncio.shield(self._pump_task)
        await asyncio.to_thread(self._pool.shutdown, wait=True)
        self._closed = True

    async def __aenter__(self):
        self._bind()
        return self

    async def __aexit__(self, *args):
        await self.close()
