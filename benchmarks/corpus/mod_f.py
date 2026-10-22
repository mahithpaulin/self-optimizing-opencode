import re

TODO = "index this"


def search(lines, pattern):
    security = re.compile(pattern)
    return [line for line in lines if security.search(line)]
