from __future__ import annotations

import unittest
from pathlib import Path


class TestDoctorEnvRegistration(unittest.TestCase):
    def test_doctor_env_registered_once_in_cli_main(self) -> None:
        """
        Regression: ensure "doctor env" subparser is registered exactly once.

        This is a static test to avoid importing CLI modules (which require optional runtime deps).
        """
        repo_root = Path(__file__).resolve().parents[1]
        cli_main = repo_root / "src" / "gst_automation" / "validation" / "cli_main.py"
        text = cli_main.read_text(encoding="utf-8")

        # Narrow match to doctor subparser block.
        needle = 'doctor_sub.add_parser("env"'
        self.assertEqual(text.count(needle), 1, f"Expected exactly one occurrence of: {needle}")


if __name__ == "__main__":
    unittest.main()

