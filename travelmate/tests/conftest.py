import os
import tempfile
from pathlib import Path

# Keep test runs away from the developer's product database (travelmate.sqlite3).
_TMP = tempfile.mkdtemp(prefix="travelmate-tests-")
os.environ["TRAVELMATE_DB"] = str(Path(_TMP) / "test.sqlite3")
