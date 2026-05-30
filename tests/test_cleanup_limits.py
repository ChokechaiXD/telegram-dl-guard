# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.state import get_uploaded_existing_candidates, mark_uploaded, remove_entry


class CleanupLimitTests(unittest.TestCase):
    def test_uploaded_candidate_query_respects_limit(self) -> None:
        paths = []
        with tempfile.TemporaryDirectory() as td:
            for idx in range(3):
                path = Path(td) / f"uploaded_{idx}.bin"
                path.write_bytes(b"abc")
                paths.append(path)
                mark_uploaded(str(path), 1000 + idx)

            try:
                rows = get_uploaded_existing_candidates(limit=2)
                self.assertLessEqual(len(rows), 2)
            finally:
                for path in paths:
                    remove_entry(str(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
