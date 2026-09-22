import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

# Every git the suite runs, the code under test's included, ignores the
# user's and the machine's git configuration: a global pre-commit hook or
# commit signing would fail the commits the fixtures make.
os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

# Nor does the Qwen Code reader read the machine's own system settings files,
# which sit outside any HOME a test sets and could name a real directory.
os.environ["QWEN_CODE_SYSTEM_SETTINGS_PATH"] = os.devnull
os.environ["QWEN_CODE_SYSTEM_DEFAULTS_PATH"] = os.devnull
