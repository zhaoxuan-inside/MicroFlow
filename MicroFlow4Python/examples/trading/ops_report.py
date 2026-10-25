"""监控/运营数据面演示：框架内置采集 → 上层聚合投影。

观测分层（平台标准 §14）：框架在运行时边界零埋点产生结构化执行记录
（attempt_started / attempt_finished / invocation_completed）；本脚本扮演
上层分析角色，消费本地演练记录生成监控指标与运营汇总。生产部署中该角色
由监控/运营平台承载，可靠业务事件经宿主提供者投递（T10/T14 协议）。

运行：PYTHONPATH=../../src python3 ops_report.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from microflow import LocalRuntime, discover  # noqa: E402
from microflow.compiler import compile_release  # noqa: E402
from microflow.values import load_json  # noqa: E402


def load_inputs():
    return {
        "browse": {"keyword": "手机"},
        "order": load_json((HERE / "input_order.json").read_text(encoding="utf-8")),
        "order_blocked": load_json((HERE / "input_order_blocked.json").read_text(encoding="utf-8")),
    }


def main():
    inputs = load_inputs()
    registry = discover([HERE / "trading_ops.py"])
    flows = load_json((HERE / "trading.project.json").read_text(encoding="utf-8"))["flows"]
    release = compile_release(registry, flows,
                              defaults={"durability": "ephemeral", "recovery": {"enabled": False}})
    runtime = LocalRuntime(release)

    runs = [("browse", inputs["browse"]),
            ("place_order", inputs["order"]),
            ("place_order", inputs["order_blocked"]),
            ("place_order", inputs["order"])]

    by_operator = {}
    orders = []
    for flow, data in runs:
        result = runtime.run(flow, data)
        for record in result.records:
            if record["event"] != "attempt_finished":
                continue
            ref = f"{record['operatorName']}@{record['operatorVersion']}"
            slot = by_operator.setdefault(ref, {"invocations": 0, "ok": 0, "failed": 0, "totalMs": 0.0})
            slot["invocations"] += 1
            slot["ok" if record["status"] == "SUCCEEDED" else "failed"] += 1
            slot["totalMs"] += record.get("durationMs") or 0.0
        order = (result.output.get("data") or {}).get("order")
        if order:
            orders.append({"orderId": order["orderId"], "status": order["status"],
                           "payable": order["payable"]})

    for slot in by_operator.values():
        slot["okRate"] = round(slot["ok"] / slot["invocations"], 4) if slot["invocations"] else 0.0
        slot["avgMs"] = round(slot["totalMs"] / slot["invocations"], 3) if slot["invocations"] else 0.0
        slot["totalMs"] = round(slot["totalMs"], 3)

    created = [o for o in orders if o["status"] == "CREATED"]
    report = {
        "protocol": "trading-ops-report-v1",
        "monitoring": {"runs": len(runs), "byOperator": dict(sorted(by_operator.items()))},
        "operations": {
            "ordersCreated": len(created),
            "ordersBlocked": len(orders) - len(created),
            "gmvCents": sum(o["payable"] for o in created),
            "orders": orders,
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
