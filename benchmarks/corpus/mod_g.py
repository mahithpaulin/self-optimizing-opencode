import json


class State:
    def load(self, text):
        return json.loads(text)


def checkpoint(state):
    return json.dumps(state, sort_keys=True)


def rollback(state):
    return State().load(state)
