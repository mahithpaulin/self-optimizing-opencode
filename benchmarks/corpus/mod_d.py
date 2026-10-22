def load_state(path):
    try:
        return open(path, encoding="utf-8").read()
    except PermissionError:
        return None


def rollback(previous):
    state = previous
    model = "deterministic"
    return state, model
