from __future__ import annotations

import os
import tempfile

# Keep tests away from the real model/project directories.
os.environ.setdefault("MUSIC2SCORE_HOME", tempfile.mkdtemp(prefix="music2score-test-"))
