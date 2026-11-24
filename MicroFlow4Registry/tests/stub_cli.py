"""A stand-in CLI for capability and gate branches the real CLI cannot reach cheaply.

The real CLI's diagnostics are covered by its own suite; these stubs prove how
*this* package behaves when the tool it depends on is incomplete or when the
framework's gate reports a negative.
"""
import json
import os
import sys

CAPABILITIES = {"protocol": "microflow-cli-v1", "implementation": "stub",
                "implementationVersion": "0.0.0",
                "commands": {name: {"args": [], "ephemeral": "required", "resultKeys": []}
                             for name in ("capabilities", "check", "operators", "policy-schema")}}

POLICY = {"protocol": "microflow-policy-schema-v1",
          "schema": {"fields": {"durability": {"type": "string"}}},
          "defaults": {"durability": "durable"},
          "merge": {"objects": "recursive"}}


def main(argv):
    command = argv[0] if argv else ""
    if command == "capabilities":
        capabilities = dict(CAPABILITIES)
        if os.getenv("STUB_MODE") == "missing":
            capabilities["commands"] = {name: capabilities["commands"][name]
                                       for name in ("capabilities",)}
        print(json.dumps(capabilities))
        return 0
    if command == "check":
        print(json.dumps({"protocol": "microflow-cli-v1", "releaseId": "stub-release",
                          "durability": "ephemeral", "flows": ["main"],
                          "diagnostics": [{"error_code": "STUB_DIAGNOSTIC",
                                           "message": "gate is not clean"}]}))
        return 0
    if command == "operators":
        print(json.dumps({"protocol": "microflow-cli-v1", "releaseId": "stub-release",
                          "durability": "ephemeral", "operators": []}))
        return 0
    if command == "policy-schema":
        print(json.dumps(POLICY))
        return 0
    print(json.dumps({"protocol": "microflow-cli-v1",
                      "diagnostic": {"error_code": "UNKNOWN_COMMAND", "message": command}}))
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
