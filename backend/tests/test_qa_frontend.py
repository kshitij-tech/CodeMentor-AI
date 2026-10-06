
import html.parser
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit


FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend"


class _AssetParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.styles = []
        self.inline_scripts = []
        self._capture_script = False
        self._script_buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            src = attrs.get("src")
            if src:
                self.scripts.append(src)
            else:
                self._capture_script = True
                self._script_buffer = []
        elif tag == "link":
            rel = (attrs.get("rel") or "").lower().split()
            href = attrs.get("href")
            if href and "stylesheet" in rel:
                self.styles.append(href)

    def handle_data(self, data):
        if self._capture_script:
            self._script_buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._capture_script:
            self.inline_scripts.append("".join(self._script_buffer))
            self._capture_script = False
            self._script_buffer = []


def _local_path(value):
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return None
    path = parsed.path
    if not path or path.startswith("#"):
        return None
    return FRONTEND_ROOT / path.lstrip("/")


class FrontendQualityTests(unittest.TestCase):
    def test_all_frontend_local_assets_resolve(self):
        missing = []
        for html_file in sorted(FRONTEND_ROOT.glob("*.html")):
            parser = _AssetParser()
            parser.feed(html_file.read_text(encoding="utf-8"))

            for ref in parser.scripts + parser.styles:
                target = _local_path(ref)
                if target is not None and not target.exists():
                    missing.append(f"{html_file.name}: {ref}")

        self.assertEqual(missing, [])

    @unittest.skipUnless(
        shutil.which("node"),
        "Node.js is required for JavaScript syntax validation.",
    )
    def test_inline_and_local_javascript_parse_with_node(self):
        failures = []
        js_files = sorted(FRONTEND_ROOT.glob("*.js"))

        with tempfile.TemporaryDirectory(prefix="codementor-js-") as temp_dir:
            temp_root = Path(temp_dir)

            for js_file in js_files:
                completed = subprocess.run(
                    ["node", "--check", str(js_file)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if completed.returncode:
                    failures.append(f"{js_file.name}: {completed.stderr.strip()}")

            for html_file in sorted(FRONTEND_ROOT.glob("*.html")):
                parser = _AssetParser()
                parser.feed(html_file.read_text(encoding="utf-8"))
                for index, source in enumerate(parser.inline_scripts):
                    if not source.strip():
                        continue
                    script_path = temp_root / f"{html_file.stem}-{index}.js"
                    script_path.write_text(source, encoding="utf-8")
                    completed = subprocess.run(
                        ["node", "--check", str(script_path)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if completed.returncode:
                        failures.append(
                            f"{html_file.name} inline script {index}: "
                            f"{completed.stderr.strip()}"
                        )

        self.assertEqual(failures, [])

    def test_application_pages_include_shared_ui_layer(self):
        application_pages = {
            "index.html",
            "auth.html",
            "dashboard.html",
            "practice.html",
            "problem.html",
            "mentor.html",
            "analytics.html",
            "career.html",
            "onboarding.html",
            "preferences.html",
            "settings.html",
        }

        missing = []
        for name in sorted(application_pages):
            page = (FRONTEND_ROOT / name).read_text(encoding="utf-8")
            if not re.search(
                r'<link[^>]+href=["\']ui\.css["\']',
                page,
                re.IGNORECASE,
            ):
                missing.append(f"{name}: ui.css")
            if not re.search(
                r'<script[^>]+src=["\']ui\.js["\']',
                page,
                re.IGNORECASE,
            ):
                missing.append(f"{name}: ui.js")

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
