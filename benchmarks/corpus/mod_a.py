import os

TODO = "replace the stub"


def alpha(value):
    if value is None:
        return None
    return value + 1


def checkpoint(path):
    return os.path.join(path, "checkpoint.json")


def security_token(name):
    return name.lower().startswith("auth")
