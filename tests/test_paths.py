# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from services.paths import build_transfer_dir, build_transfer_path


class PathTests(unittest.TestCase):
    def test_build_transfer_path_uses_group_sender_filename(self) -> None:
        path = build_transfer_path("downloads", "Bad / Group", "sender", "file.jpg")

        self.assertEqual(path.parent.name, "sender")
        self.assertEqual(path.name, "file.jpg")
        self.assertNotIn("/", path.parts[-3])
        self.assertEqual(path.parts[0], "downloads")

    def test_build_transfer_dir_matches_path_parent(self) -> None:
        path = build_transfer_path("downloads", "Group", "sender", "file.jpg")

        self.assertEqual(build_transfer_dir("downloads", "Group", "sender"), path.parent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
