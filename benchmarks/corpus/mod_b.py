import subprocess


class Workspace:
    def run(self, argv, timeout=30):
        if not argv:
            raise ValueError("empty command")
        return subprocess.run(argv, timeout=timeout)


def run_job(argv):
    workspace = Workspace()
    return workspace.run(argv)
