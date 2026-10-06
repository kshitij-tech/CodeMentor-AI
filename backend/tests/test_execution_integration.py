from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

from backend import execution


DOCKER_IMAGE = "codementor-multi-runtime:test"
DOCKER_AVAILABLE = bool(shutil.which("docker"))
if DOCKER_AVAILABLE:
    try:
        DOCKER_AVAILABLE = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        DOCKER_AVAILABLE = False


@unittest.skipUnless(DOCKER_AVAILABLE, "Docker daemon is unavailable")
class DockerExecutionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).parents[2]
        image = subprocess.run(
            ["docker", "image", "inspect", DOCKER_IMAGE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        if image.returncode != 0:
            built = subprocess.run(
                [
                    "docker",
                    "build",
                    "-t",
                    DOCKER_IMAGE,
                    "-f",
                    str(root / "docker" / "multi-runtime" / "Dockerfile"),
                    str(root / "docker" / "multi-runtime"),
                ],
                timeout=900,
                check=False,
            )
            if built.returncode != 0:
                raise RuntimeError("Could not build the multi-runtime execution image.")
        cls.previous_image = execution.EXECUTION_DOCKER_IMAGE
        execution.EXECUTION_DOCKER_IMAGE = DOCKER_IMAGE

    @classmethod
    def tearDownClass(cls):
        execution.EXECUTION_DOCKER_IMAGE = cls.previous_image

    def _run(self, language: str, source: str, *, memory_limit_mb: int | None = 256):
        cases = [
            {"input": "21\n", "expected_output": "42\n"},
            {"input": "5\n", "expected_output": "10\n"},
        ]
        return execution.run_language_stdio_tests(
            source,
            language,
            cases,
            time_limit_seconds=2,
            memory_limit_mb=memory_limit_mb,
        )

    def test_all_supported_languages_execute_stdin_stdout(self):
        sources = {
            "Python": "import sys\nprint(int(sys.stdin.read()) * 2)\n",
            "C++": (
                "#include <iostream>\n"
                "int main(){ long long x; std::cin >> x; std::cout << x * 2 << '\\n'; }\n"
            ),
            "Java": (
                "import java.util.Scanner;\n"
                "public class Main { public static void main(String[] args) { "
                "Scanner s = new Scanner(System.in); System.out.println(s.nextLong() * 2); } }\n"
            ),
            "JavaScript": "const fs=require('fs'); const x=Number(fs.readFileSync(0,'utf8').trim()); console.log(x*2);\n",
            "TypeScript": "import * as fs from 'fs'; const x: number = Number(fs.readFileSync(0,'utf8').trim()); console.log(x*2);\n",
            "Go": (
                "package main\nimport \"fmt\"\nfunc main(){ var x int64; fmt.Scan(&x); fmt.Println(x*2) }\n"
            ),
            "Rust": (
                "use std::io::{self, Read};\n"
                "fn main(){ let mut s=String::new(); io::stdin().read_to_string(&mut s).unwrap(); "
                "let x:i64=s.trim().parse().unwrap(); println!(\"{}\", x*2); }\n"
            ),
        }
        for language, source in sources.items():
            with self.subTest(language=language):
                results = self._run(language, source)
                self.assertEqual([r.status for r in results], ["Passed", "Passed"])
                self.assertEqual([r.actual.strip() for r in results], ["42", "10"])

    def test_compilation_error_is_reported(self):
        results = self._run("C++", "int main( {\n")
        self.assertTrue(all(r.status == "Compilation Error" for r in results))

    def test_runtime_error_is_reported(self):
        results = self._run("Python", "print(1 / 0)\n")
        self.assertTrue(all(r.status == "Runtime Error" for r in results))

    def test_wrong_answer_is_reported(self):
        results = self._run(
            "Python",
            "import sys\nprint(int(sys.stdin.read()) * 3)\n",
        )
        self.assertTrue(all(r.status == "Wrong Answer" for r in results))

    def test_infinite_loop_hits_time_limit(self):
        results = self._run("Python", "while True:\n    pass\n")
        self.assertTrue(all(r.status == "Time Limit Exceeded" for r in results))

    def test_memory_limit_is_enforced(self):
        results = self._run(
            "Python",
            "data = bytearray(256 * 1024 * 1024)\nprint(len(data))\n",
            memory_limit_mb=64,
        )
        self.assertTrue(all(r.status == "Memory Limit Exceeded" for r in results))

    def test_output_limit_is_enforced(self):
        results = self._run("Python", "print('x' * 100000)\n")
        self.assertTrue(all(r.status == "Runtime Error" for r in results))
        self.assertTrue(
            all("output limit" in (r.message or "").lower() for r in results)
        )

    def test_network_is_disabled(self):
        source = (
            "import socket\n"
            "socket.create_connection(('1.1.1.1', 80), timeout=0.5)\n"
        )
        results = self._run("Python", source)
        self.assertTrue(all(r.status == "Runtime Error" for r in results))

    def test_workspace_is_read_only(self):
        source = "open('/workspace/escape.txt', 'w').write('pwned')\n"
        results = self._run("Python", source)
        self.assertTrue(all(r.status == "Runtime Error" for r in results))

    def test_test_results_remain_independent(self):
        source = (
            "import sys\nx=int(sys.stdin.read())\n"
            "print(x if x == 21 else x * 999)\n"
        )
        results = self._run("Python", source)
        self.assertEqual(results[0].status, "Passed")
        self.assertEqual(results[1].status, "Wrong Answer")
