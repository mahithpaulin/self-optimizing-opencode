import json

from pathlib import Path


def dump_record(record):
    assert isinstance(record, dict)
    return json.dumps(record, sort_keys=True)


def digest_file(path):
    return __import__("hashlib").sha256(Path(path).read_bytes()).hexdigest()
