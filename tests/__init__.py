import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

# Every git the suite runs, the code under test's included, ignores the
# user's and the machine's git configuration: a global pre-commit hook or
# commit signing would fail the commits the fixtures make.
os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
