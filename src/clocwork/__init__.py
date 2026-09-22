"""clocwork: lines, agents and tokens over a repository's whole history."""

import sys as _sys

# Every way in (the console script, the clone's shim, the zipapp, python -m)
# imports this package before any module that needs 3.11, such as config's
# tomllib. pip checks requires-python; the others would stop in a traceback.
# Kept to syntax an old interpreter can parse.
if _sys.version_info < (3, 11):
    _v = _sys.version_info
    _sys.stderr.write("clocwork: needs Python 3.11 or later; this is Python %d.%d.%d (%s)\n"
                      % (_v[0], _v[1], _v[2], _sys.executable))
    raise SystemExit(2)

__version__ = "0.2.0"
