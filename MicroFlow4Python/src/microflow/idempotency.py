"""Business identity primitives; mutations compose into the execution StateBatch."""
from collections.abc import Mapping
from dataclasses import dataclass
import math
from .errors import ContractError, PersistenceError
from .paths import Field, get, parse
from .values import MISSING, digest, thaw

OPERATION_PROTOCOL = 'microflow-business-operation-v1'


@dataclass(frozen=True)
class OperationScope:
    tenant: str
    domain: str
    operation: str
    semantic_version: str

    def __post_init__(self):
        for value in (self.tenant, self.domain, self.operation, self.semantic_version):
            if type(value) is not str or not value or len(value) > 256:
                raise ContractError('INVALID_OPERATION_SCOPE', 'Business scope fields must be bounded nonempty strings')

    def identify(self, data, key_paths):
        if not isinstance(key_paths, (list, tuple)):
            raise ContractError('INVALID_OPERATION_KEY', 'Business key paths must be an array')
        values = []
        for path in key_paths:
            tokens = parse(path)
            if len(tokens) < 2 or tokens[0] != Field('input'):
                raise ContractError('INVALID_OPERATION_KEY', 'Business keys must reference input fields')
            value = get({'input': data}, tokens)
            if value is MISSING or value is None:
                raise ContractError('MISSING_OPERATION_KEY', 'Business operation key is missing or null')
            values.append(value)
        if not values:
            raise ContractError('MISSING_OPERATION_KEY', 'At least one stable business key is required')
        operation_id = digest({'tenant': self.tenant, 'domain': self.domain, 'operation': self.operation, 'keys': values})
        request_digest = digest({'semantic_version': self.semantic_version, 'input': data})
        return operation_id, request_digest


def load_operation(view, operation_id, request_digest=None):
    key = 'operation/' + operation_id
    if key not in view.records:
        return None
    record = view.records[key]
    required = {'protocol', 'operation_id', 'request_digest', 'status', 'origin', 'created_at', 'observed_at', 'retain_until', 'result'}
    if (not isinstance(record, Mapping) or record.get('protocol') != OPERATION_PROTOCOL
            or not required <= record.keys()
            or record.get('operation_id') != operation_id
            or record.get('status') not in ('IN_PROGRESS', 'SUCCEEDED', 'FAILED', 'IN_DOUBT')):
        raise PersistenceError('INVALID_OPERATION_RECORD', 'Unsupported business operation record')
    origin = record['origin']
    if (type(record['request_digest']) is not str or not record['request_digest']
            or not isinstance(origin, Mapping)
            or not {'execution_id', 'node_id', 'release_id', 'owner', 'attempt_epoch'} <= origin.keys()
            or any(type(origin[name]) is not str or not origin[name] for name in ('execution_id', 'node_id', 'release_id'))
            or type(origin['attempt_epoch']) is not int or origin['attempt_epoch'] < 1
            or type(record['created_at']) not in (int, float) or not math.isfinite(record['created_at']) or record['created_at'] < 0
            or type(record['observed_at']) not in (int, float) or not math.isfinite(record['observed_at'])
            or record['observed_at'] < record['created_at']):
        raise PersistenceError('INVALID_OPERATION_RECORD', 'Invalid business operation provenance')
    if record['status'] in ('SUCCEEDED', 'FAILED'):
        result, expiry = record['result'], record['retain_until']
        if (type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry < record['observed_at']
                or not isinstance(result, Mapping) or not {'status', 'data', 'error', 'resolution'} <= result.keys()
                or (record['status'] == 'SUCCEEDED' and result['status'] != 'SUCCEEDED')
                or (record['status'] == 'FAILED' and result['status'] not in ('FAILED', 'CANCELLED'))
                or type(result['resolution']) is not str
                or (result['status'] == 'SUCCEEDED' and result['error'] is not None)
                or (result['status'] != 'SUCCEEDED' and (not isinstance(result['error'], Mapping)
                    or type(result['error'].get('code')) is not str or not result['error']['code']))):
            raise PersistenceError('INVALID_OPERATION_RECORD', 'Invalid confirmed business result')
    elif record['retain_until'] is not None or (record['status'] == 'IN_PROGRESS' and record['result'] is not None):
        raise PersistenceError('INVALID_OPERATION_RECORD', 'Unconfirmed operations cannot expire or publish results')
    if request_digest is not None and record['request_digest'] != request_digest:
        raise ContractError('IDEMPOTENCY_CONFLICT', 'Business key already belongs to a different request')
    return thaw(record)
