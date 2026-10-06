import unittest

from deployment.qt_rehearsal.cli import build_parser


class CliTests(unittest.TestCase):
    def test_restore_has_no_create_clean_or_arbitrary_pg_restore_option(self):
        parser = build_parser()
        valid = parser.parse_args([
            "restore",
            "--root", "/dev/shm/algolens-qt-rehearsal.ABCDEF",
            "--pg-bin", "/opt/pg16/bin",
            "--database", "qt_rehearsal_baseline",
            "--archive", "/tmp/synthetic.dump",
            "--archive-sha256", "a" * 64,
        ])
        self.assertEqual(valid.command, "restore")
        for option in ("--create", "--clean", "-C"):
            with self.subTest(option=option), self.assertRaises(SystemExit):
                parser.parse_args([
                    "restore",
                    "--root", "/dev/shm/algolens-qt-rehearsal.ABCDEF",
                    "--pg-bin", "/opt/pg16/bin",
                    "--database", "qt_rehearsal_baseline",
                    "--archive", "/tmp/synthetic.dump",
                    "--archive-sha256", "a" * 64,
                    option,
                ])

    def test_all_mutating_commands_require_explicit_root_and_pg_bin(self):
        parser = build_parser()
        for command in ("init", "restore", "apply-manifest", "verify-roles", "cleanup"):
            with self.subTest(command=command), self.assertRaises(SystemExit):
                parser.parse_args([command])

    def test_input_lock_validation_is_an_explicit_non_database_command(self):
        options = build_parser().parse_args([
            "validate-input-lock",
            "--input-lock", "/tmp/input-lock.json",
        ])
        self.assertEqual(options.command, "validate-input-lock")
        self.assertEqual(str(options.input_lock), "/tmp/input-lock.json")


if __name__ == "__main__":
    unittest.main()
