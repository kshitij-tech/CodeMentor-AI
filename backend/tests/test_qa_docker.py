
import os
import shutil
import subprocess
import unittest


IMAGE = os.getenv("CODEMENTOR_DOCKER_IMAGE")


class DockerQualityTests(unittest.TestCase):
    def test_dockerfile_declares_workspace_for_unprivileged_runner(self):
        from pathlib import Path

        dockerfile = (
            Path(__file__).resolve().parents[2]
            / "docker"
            / "multi-runtime"
            / "Dockerfile"
        ).read_text(encoding="utf-8")

        self.assertIn("WORKDIR /workspace", dockerfile)
        self.assertIn("USER 65532:65532", dockerfile)
        self.assertNotIn("/runner/smoke.cpp", dockerfile)
        self.assertNotIn("USER root", dockerfile)

    @unittest.skipUnless(
        IMAGE and shutil.which("docker"),
        "Set CODEMENTOR_DOCKER_IMAGE to run live multi-runtime smoke tests.",
    )
    def test_live_image_can_compile_and_run_cpp_from_workspace(self):
        command = (
            "printf '#include <iostream>\\nint main(){int x; std::cin >> x; "
            "std::cout << x * 2 << \"\\\\n\";}\\n' > /tmp/smoke.cpp && "
            "g++ -std=c++20 /tmp/smoke.cpp -o /tmp/smoke && "
            "printf '21\\n' | /tmp/smoke"
        )
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                IMAGE,
                "sh",
                "-lc",
                command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "42")

    @unittest.skipUnless(
        IMAGE and shutil.which("docker"),
        "Set CODEMENTOR_DOCKER_IMAGE to run live multi-runtime smoke tests.",
    )
    def test_live_image_exposes_all_declared_runtimes(self):
        command = (
            "python --version && g++ --version && javac -version && "
            "node --version && tsc --version && go version && rustc --version"
        )
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                IMAGE,
                "bash",
                "-lc",
                command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Python", completed.stdout)
        self.assertIn("g++", completed.stdout)
        self.assertIn("javac", completed.stdout)
        self.assertIn("v", completed.stdout)
        self.assertIn("go version", completed.stdout)
        self.assertIn("rustc", completed.stdout)


if __name__ == "__main__":
    unittest.main()
