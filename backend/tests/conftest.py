"""Global test configuration: isolate all LYRA data from the user's real databases."""

import os
import tempfile

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="lyra-test-data-")
os.environ["LYRA_DATA_DIR"] = _TEST_DATA_DIR
os.environ["LYRA_AUTO_MIGRATE"] = "false"
