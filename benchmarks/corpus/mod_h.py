import subprocess


def main(argv):
    if not argv:
        return None
    try:
        result = subprocess.run(argv, timeout=10)
    except Exception:
        return None
    assert result is not None
    return result
