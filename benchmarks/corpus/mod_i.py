import json


def proposal(model, workspace):
    payload = {"model": model, "workspace": workspace, "security": "unchanged"}
    return json.dumps(payload, sort_keys=True)
