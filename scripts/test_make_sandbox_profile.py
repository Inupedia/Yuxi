"""Make targets must activate only the configured sandbox profile."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class MakeSandboxProfileTests(unittest.TestCase):
    """Verify Compose profile selection without starting containers."""

    def test_default_enables_container_profile(self):
        self.assertEqual(self._command(), "docker compose --profile container down")

    def test_cube_in_env_file_does_not_enable_container_runner(self):
        self.assertEqual(self._command(env_file="SANDBOX_BACKEND=cube\n"), "docker compose down")

    def test_uppercase_cube_matches_backend_normalization(self):
        self.assertEqual(
            self._command(env_file='SANDBOX_BACKEND="CUBE" # cube mode\n'),
            "docker compose down",
        )

    def test_environment_backend_overrides_env_file(self):
        self.assertEqual(
            self._command(
                env_file="SANDBOX_BACKEND=container\n",
                environment={"SANDBOX_BACKEND": "cube"},
            ),
            "docker compose down",
        )

    def test_explicit_compose_override_is_preserved(self):
        self.assertEqual(
            self._command(environment={"COMPOSE": "docker compose --profile custom"}),
            "docker compose --profile custom down",
        )

    def test_invalid_backend_fails_before_compose_runs(self):
        result = self._run_make(env_file="SANDBOX_BACKEND=invalid\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SANDBOX_BACKEND must be cube or container", result.stderr)

    def _command(
        self,
        *,
        env_file: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> str:
        result = self._run_make(env_file=env_file, environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def _run_make(
        self,
        *,
        env_file: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="yuxi-make-profile-") as directory:
            context = Path(directory)
            (context / "Makefile").write_bytes((root / "Makefile").read_bytes())
            (context / "backend").mkdir()
            (context / "scripts").mkdir()
            (context / "scripts/compose_profile.py").write_bytes((root / "scripts/compose_profile.py").read_bytes())
            (context / "backend/.python-version").write_text("3.12\n", encoding="utf-8")
            if env_file is not None:
                (context / ".env").write_text(env_file, encoding="utf-8")
            env = os.environ.copy()
            env.pop("SANDBOX_BACKEND", None)
            env.pop("COMPOSE", None)
            env.update(environment or {})
            result = subprocess.run(
                ["make", "-n", "down"],
                cwd=context,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            return result
