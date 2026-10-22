import unittest

from microflow.errors import ContractError, PersistenceError
from microflow.persistence import Capabilities
from microflow.policy import resolve, describe_policy, validate_policy, DEFAULTS, seconds
from microflow.values import thaw


LOCAL = {"durability": "ephemeral", "recovery": {"enabled": False}}
DURABLE = Capabilities(atomic_batch=True, conditional_write=True, request_deduplication=True,
                       durable_ack=True, consistent_recovery=True)


class PolicyTests(unittest.TestCase):
    def test_schema_defaults_are_valid_and_descriptions_are_independent(self):
        description = describe_policy()
        self.assertEqual(description["protocol"], "microflow-policy-schema-v1")
        validate_policy(description["defaults"])
        self.assertEqual(description["schema"]["properties"]["timeout"]["properties"]["attempt"]["type"], "duration")
        description["defaults"]["cache"]["enabled"] = True
        description["schema"]["properties"].clear()
        self.assertFalse(describe_policy()["defaults"]["cache"]["enabled"])
        with self.assertRaises(TypeError):
            DEFAULTS["cache"]["enabled"] = True

    def test_every_leaf_rejects_null_even_when_overridden(self):
        def leaves(config, prefix=()):
            for key, value in config.items():
                if isinstance(value, dict):
                    yield from leaves(value, prefix + (key,))
                else:
                    yield prefix + (key,)
        for path in leaves(thaw(DEFAULTS)):
            bad, cursor = {}, None
            cursor = bad
            for key in path[:-1]:
                cursor[key] = {}
                cursor = cursor[key]
            cursor[path[-1]] = None
            with self.subTest(path=path), self.assertRaises(ContractError):
                resolve(bad, thaw(DEFAULTS), LOCAL)

    def test_shape_checks_inactive_fields_and_malformed_overrides(self):
        for bad in ({"cache": {"enabled": False, "ttl": "never"}},
                    {"cache": {"key_paths": ["bad[-1]"]}},
                    {"idempotency": {"enabled": False, "key_paths": [42]}},
                    {"retry": {"retry_after_fallback": 1}}, {"persistence_binding": []}):
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                resolve(LOCAL, bad)
        for overrides in ([], False, ""):
            with self.subTest(overrides=overrides), self.assertRaises(ContractError):
                resolve(LOCAL, overrides=overrides)

    def test_checkpoint_policy_is_merged_and_hashed(self):
        default = resolve(LOCAL)
        explicit = resolve(LOCAL, {"checkpoint_policy": "explicit"})
        self.assertEqual(default["checkpoint_policy"], "operator")
        self.assertNotEqual(default.policy_digest, explicit.policy_digest)
        with self.assertRaises(ContractError):
            resolve(LOCAL, {"checkpoint_policy": "automatic"})
        with self.assertRaisesRegex(ContractError, "FORBIDDEN_OVERRIDE"):
            resolve(LOCAL, overrides={"checkpoint_policy": "explicit"})
        self.assertEqual(resolve(LOCAL, overrides={"checkpoint_policy": "explicit"},
            allowed_overrides={"checkpoint_policy"})["checkpoint_policy"], "explicit")

    def test_duration_shapes_and_error_paths(self):
        for value, expected in ((1, 1), (0.5, .5), ("50ms", .05), ("1m", 60), ("2h", 7200), ("1d", 86400)):
            self.assertEqual(seconds(value), expected)
            validate_policy({"timeout": {"attempt": value}})
        for value in (True, 0, -1, "0s", "NaN", "1w", " 1s", {}, []):
            with self.subTest(value=value), self.assertRaises(ContractError) as caught:
                resolve(LOCAL, {"timeout": {"attempt": value}})
            self.assertEqual(caught.exception.diagnostic.path, "policy.timeout.attempt")

    def test_four_layers_false_arrays_and_stable_digest(self):
        result = resolve(LOCAL, {"cache": {"enabled": True}, "resource_policy": {"keys": ["a"]}},
                         {"cache": {"enabled": False}}, overrides={"resource_policy": {"keys": []}},
                         allowed_overrides={"resource_policy.keys"})
        self.assertFalse(result["cache"]["enabled"])
        self.assertEqual(result["resource_policy"]["keys"], ())
        self.assertEqual(result.policy_digest, resolve(thaw(result.values)).policy_digest)
        with self.assertRaises(TypeError):
            result.values["cache"]["enabled"] = True

    def test_leaf_override_cannot_change_sibling(self):
        with self.assertRaises(ContractError):
            resolve(LOCAL, overrides={"cache": {"enabled": False, "ttl": "1s"}},
                    allowed_overrides={"cache.enabled"})

    def test_missing_or_insufficient_provider_refuses_durable(self):
        for provider in (None, Capabilities()):
            with self.subTest(provider=provider), self.assertRaises((ContractError, PersistenceError)):
                resolve(provider_capabilities=provider)
        self.assertEqual(resolve(provider_capabilities=DURABLE)["durability"], "durable")

    def test_unknown_null_and_invalid_combinations(self):
        for bad in ({"cache": None}, {"cache": {"enabled": None}}, {"cache": {"other": 1}},
                    {"execution_mode": "async"}, {"timeout": {"attempt": 0}},
                    {"retry": {"max_attempts": True}}, {"concurrency": 0}):
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                resolve(LOCAL, bad)

    def test_write_capabilities_and_cache_constraints(self):
        for policy in ({"cache": {"enabled": True}}, {"retry": {"max_attempts": 2}},
                       {"idempotency": {"enabled": True, "key_paths": ["input.key"]}}):
            with self.subTest(policy=policy), self.assertRaises(ContractError):
                resolve(LOCAL, policy, capabilities={"effect": "write", "idempotency_support": "none"})

    def test_paths_and_owner_scope_are_validated(self):
        with self.assertRaises(ContractError):
            resolve(LOCAL, {"resource_policy": {"keys": ["bad[-1]"]}})
        with self.assertRaises(PersistenceError):
            DURABLE.require_ownership("cluster")
