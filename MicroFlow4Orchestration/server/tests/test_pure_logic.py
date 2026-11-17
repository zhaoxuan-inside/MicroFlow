"""控制面纯逻辑测试：哈希对齐、实验分桶、灰度解析、告警规则求值（无 PostgreSQL）。"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.alerting import evaluate_rules
from app.configcenter import gray_selected, validate_gray
from app.experiments import bucket, decide, pick_variant
from app.lifecycle import config_content_hash, flow_digest_of

NOW = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)


def record(status, minutes_ago=0, scenario="s1", node="n1"):
    return {"scenario_code": scenario, "env": "dev", "node_id": node, "status": status,
            "reported_at": (NOW - timedelta(minutes=minutes_ago)).isoformat()}


# ---------------------------------------------------------------------------
# T12 对齐：config_hash 内容寻址
# ---------------------------------------------------------------------------
class TestConfigHash:
    def test_deterministic_across_calls_and_key_order(self):
        graph = {"entry_node": "a", "nodes": [{"id": "a"}], "edges": []}
        reordered = {"edges": [], "nodes": [{"id": "a"}], "entry_node": "a"}
        assert config_content_hash(graph) == config_content_hash(reordered)
        assert len(config_content_hash(graph)) == 64

    def test_content_change_changes_digest(self):
        graph = {"entry_node": "a", "nodes": [{"id": "a"}], "edges": []}
        changed = {"entry_node": "a", "nodes": [{"id": "a"}, {"id": "b"}], "edges": []}
        assert config_content_hash(graph) != config_content_hash(changed)

    def test_flow_digest_is_none_without_microflow_or_hex_with_it(self):
        graph = {"entry_node": "a", "exit_node": "a",
                 "nodes": [{"id": "a", "kind": "OPERATOR", "operator": "x", "operator_version": "1"}],
                 "edges": []}
        digest = flow_digest_of(graph)
        try:
            import microflow.platform_graph  # noqa: F401
            available = True
        except ImportError:
            available = False
        if available:
            assert digest and len(digest) == 64
        else:
            assert digest is None


# ---------------------------------------------------------------------------
# 实验域分桶
# ---------------------------------------------------------------------------
class TestExperimentDecision:
    def test_bucket_is_deterministic_and_bounded(self):
        assert bucket("exp", "user-1") == bucket("exp", "user-1")
        assert bucket("exp", "user-1") != bucket("other", "user-1")
        assert 0 <= bucket("exp", "user-1") < 100

    def test_pick_variant_respects_weights(self):
        variants = [{"key": "control", "weight": 90}, {"key": "treatment", "weight": 10}]
        picks = [pick_variant(value, variants) for value in range(1000)]
        share = picks.count("treatment") / len(picks)
        assert 0.05 < share < 0.15  # 权重 10% 的近似分摊
        zero = [{"key": "a", "weight": 0}, {"key": "b", "weight": 0}]
        assert pick_variant(5, zero) == "a"  # 全零权重取首个

    def test_decide_gates_on_status_and_traffic(self):
        experiment = {"key": "exp", "status": "RUNNING", "traffic_percent": 100,
                      "variants": [{"key": "v1", "weight": 1}]}
        decision = decide(experiment, "any-uid")
        assert decision["in_experiment"] is True and decision["variant"] == "v1"
        stopped = decide({**experiment, "status": "STOPPED"}, "any-uid")
        assert stopped["in_experiment"] is False and stopped["reason"].startswith("status:")
        low = decide({**experiment, "traffic_percent": 0}, "any-uid")
        assert low["in_experiment"] is False

    def test_decide_split_is_deterministic_per_uid(self):
        experiment = {"key": "exp", "status": "RUNNING", "traffic_percent": 50,
                      "variants": [{"key": "a", "weight": 1}, {"key": "b", "weight": 1}]}
        first = decide(experiment, "uid-42")
        again = decide(experiment, "uid-42")
        assert first == again


# ---------------------------------------------------------------------------
# 配置中心灰度
# ---------------------------------------------------------------------------
class TestGrayResolution:
    def test_whitelist_direct_pass_and_percent_bucketing(self):
        assert gray_selected("vip", {"percent": 0, "whitelist": ["vip"]}) is True
        full = {"percent": 100, "whitelist": []}
        assert gray_selected("anyone", full) is True
        none = {"percent": 0, "whitelist": []}
        assert gray_selected("anyone", none) is False

    def test_percent_bucketing_is_deterministic(self):
        gray = {"percent": 50, "whitelist": []}
        first, again = gray_selected("u", gray), gray_selected("u", gray)
        assert first == again

    def test_validate_gray_rejects_unknown_and_out_of_range(self):
        assert validate_gray(None) == {}
        assert validate_gray({"percent": 30, "whitelist": ["a"]}) == {"percent": 30, "whitelist": ["a"]}
        with pytest.raises(ValueError):
            validate_gray({"percent": 30, "evil": 1})
        with pytest.raises(ValueError):
            validate_gray({"percent": 101})
        with pytest.raises(ValueError):
            validate_gray({"percent": 5, "whitelist": [1]})


# ---------------------------------------------------------------------------
# 告警规则求值
# ---------------------------------------------------------------------------
class TestAlertRuleEvaluation:
    def test_consecutive_failures_fires_on_trailing_losses(self):
        rules = [{"id": "r1", "name": "连败", "kind": "consecutive_failures", "target": "*",
                  "threshold": 3, "window_minutes": 60, "enabled": True}]
        records = [record("SUCCESS", 50), record("FAILED", 40), record("FAILED", 30),
                   record("FAILED", 20)]
        fired = evaluate_rules(rules, records, now=NOW)
        assert len(fired) == 1
        assert fired[0]["scope_key"] == "scenario:*"
        assert fired[0]["detail"]["trail"] == 3

    def test_success_resets_trail(self):
        rules = [{"id": "r1", "name": "连败", "kind": "consecutive_failures", "target": "*",
                  "threshold": 2, "window_minutes": 60, "enabled": True}]
        records = [record("FAILED", 30), record("SUCCESS", 20), record("FAILED", 10)]
        assert evaluate_rules(rules, records, now=NOW) == []

    def test_error_rate_over_window(self):
        rules = [{"id": "r2", "name": "错误率", "kind": "error_rate", "target": "*",
                  "threshold": 50, "window_minutes": 10, "enabled": True}]
        in_window = [record("FAILED", 5), record("FAILED", 3), record("SUCCESS", 2)]
        outside = [record("FAILED", 60)]
        fired = evaluate_rules(rules, in_window + outside, now=NOW)
        assert len(fired) == 1
        assert fired[0]["detail"]["total"] == 3
        assert fired[0]["severity"] == "warning"

    def test_disabled_rules_and_target_scoping(self):
        rules = [{"id": "r3", "name": "关闭的", "kind": "consecutive_failures", "target": "*",
                  "threshold": 1, "window_minutes": 60, "enabled": False},
                 {"id": "r4", "name": "定向", "kind": "consecutive_failures", "target": "other",
                  "threshold": 1, "window_minutes": 60, "enabled": True}]
        records = [record("FAILED", 10)]
        assert evaluate_rules(rules, records, now=NOW) == []

    def test_zero_threshold_never_fires(self):
        rules = [{"id": "r5", "name": "阈值0", "kind": "error_rate", "target": "*",
                  "threshold": 0, "window_minutes": 60, "enabled": True}]
        assert evaluate_rules(rules, [record("FAILED")], now=NOW) == []

    def test_empty_window_does_not_divide_by_zero(self):
        rules = [{"id": "r6", "name": "错误率", "kind": "error_rate", "target": "*",
                  "threshold": 10, "window_minutes": 60, "enabled": True}]
        assert evaluate_rules(rules, [], now=NOW) == []
