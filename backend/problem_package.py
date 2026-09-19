from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml


class ProblemPackageError(ValueError):
    """Raised when a problem package cannot be imported safely."""


@dataclass(frozen=True)
class PackageTestCase:
    name: str
    input_data: str
    expected_output: str
    visibility: str
    validator_flags: list[str]


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ProblemPackageError(f"Unsafe package path: {name}")
    return path


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return value[:110] or "imported-problem"


def _localized_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("en", "en-US"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
        for item in value.values():
            if isinstance(item, str) and item.strip():
                return item.strip()
    return ""


def _source_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " / ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return " / ".join(str(item).strip() for item in value.values() if str(item).strip())
    return ""


def _strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return html.unescape(re.sub(r"[ \t]+", " ", value)).strip()


def _strip_latex(value: str) -> str:
    value = re.sub(r"(?m)^\s*%.*$", "", value)
    value = re.sub(r"\\(?:begin|end)\{[^}]+\}", "\n", value)
    value = re.sub(r"\\(?:textbf|textit|emph|underline|textrm)\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\\(?:section|subsection|subsubsection)\*?\{([^{}]*)\}", r"\n\1\n", value)
    value = re.sub(r"\\(?:paragraph)\*?\{([^{}]*)\}", r"\n\1\n", value)
    value = re.sub(r"\\[a-zA-Z]+(?:\[[^\]]*\])?\s*", "", value)
    value = value.replace("~", " ")
    value = re.sub(r"[{}]", "", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _metadata_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _extract_statement_title(statement: str) -> str | None:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", statement)
    return match.group(1).strip() if match else None


def _read_time_limit(files: dict[str, bytes], limits: dict[str, Any]) -> float:
    value = limits.get("time_limit")
    if value is None and ".timelimit" in files:
        raw = files[".timelimit"].decode("utf-8", errors="replace").strip()
        value = raw.splitlines()[0].strip() if raw else None
    try:
        return float(value) if value is not None else 2.0
    except (TypeError, ValueError):
        return 2.0


def _statement_from_files(files: dict[str, bytes]) -> tuple[str, str | None]:
    candidates = [
        "problem.html",
        "problem.md",
        "problem.txt",
    ]
    for candidate in candidates:
        if candidate in files:
            raw = files[candidate].decode("utf-8", errors="replace")
            return (_strip_html(raw) if candidate.endswith(".html") else raw.strip(), candidate)

    statement_files = sorted(
        path for path in files
        if path.startswith("problem_statement/")
        and PathLikeSuffix(path)
    )
    preferred = [
        path for path in statement_files if path.endswith((".md", ".html", ".txt"))
    ] + [path for path in statement_files if path.endswith(".tex")]

    for path in preferred:
        raw = files[path].decode("utf-8", errors="replace")
        if path.endswith(".html"):
            raw = _strip_html(raw)
        elif path.endswith(".tex"):
            raw = _strip_latex(raw)
        return raw.strip(), path

    pdfs = [path for path in files if path.startswith("problem_statement/") and path.endswith(".pdf")]
    if "problem.pdf" in files or pdfs:
        return (
            "The problem statement is included as a PDF in the imported package. "
            "PDF rendering will be added to the package viewer.",
            "problem.pdf" if "problem.pdf" in files else pdfs[0],
        )

    raise ProblemPackageError("No supported problem statement file was found.")


def PathLikeSuffix(path: str) -> bool:
    return path.endswith((".md", ".html", ".txt", ".tex", ".pdf"))


def _parse_domjudge_ini(raw: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _find_rooted_files(raw_files: dict[str, bytes]) -> dict[str, bytes]:
    cleaned = {_safe_member_path(name): content for name, content in raw_files.items()}
    if PurePosixPath("problem.yaml") in cleaned:
        root = PurePosixPath("")
    else:
        problem_paths = [path for path in cleaned if path.name == "problem.yaml"]
        if not problem_paths:
            raise ProblemPackageError("Package must contain problem.yaml.")
        root = problem_paths[0].parent

    result: dict[str, bytes] = {}
    for path, content in cleaned.items():
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if str(relative):
            result[str(relative)] = content
    if "problem.yaml" not in result:
        raise ProblemPackageError("Could not determine package root.")
    return result


def _load_package_bytes(raw_files: dict[str, bytes]) -> dict[str, bytes]:
    return _find_rooted_files(raw_files)



def _validator_flags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        value = value.get("flags", [])
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value]
    return []


def _test_group_config(files: dict[str, bytes], input_path: str) -> dict[str, Any]:
    path = PurePosixPath(input_path)
    candidates = [str(path.with_suffix(".yaml"))]

    parent = path.parent
    while True:
        candidates.append(str(parent / "test_group.yaml"))
        if str(parent) == ".":
            break
        parent = parent.parent

    for candidate in candidates:
        if candidate not in files:
            continue
        try:
            data = yaml.safe_load(files[candidate].decode("utf-8", errors="replace")) or {}
        except yaml.YAMLError as exc:
            raise ProblemPackageError(f"Invalid YAML in {candidate}: {exc}") from exc
        if not isinstance(data, dict):
            raise ProblemPackageError(f"{candidate} must contain a YAML mapping.")
        return data

    return {}

def _extract_test_cases(files: dict[str, bytes]) -> list[PackageTestCase]:
    test_cases: list[PackageTestCase] = []
    for path, data in sorted(files.items()):
        if not path.startswith("data/") or not path.endswith(".in"):
            continue
        relative = PurePosixPath(path)
        parts = relative.parts
        if len(parts) < 3 or parts[1] not in {"sample", "secret"}:
            continue

        answer_path = path[:-3] + ".ans"
        if answer_path not in files:
            raise ProblemPackageError(
                f"Missing answer file for test case: {path}"
            )

        config = _test_group_config(files, path)
        test_cases.append(
            PackageTestCase(
                name=path[5:-3],
                input_data=data.decode("utf-8", errors="replace"),
                expected_output=files[answer_path].decode("utf-8", errors="replace"),
                visibility=parts[1],
                validator_flags=_validator_flags(config.get("output_validator_args")),
            )
        )

    if not test_cases:
        raise ProblemPackageError(
            "No sample/secret .in/.ans test cases were found in data/."
        )
    return test_cases


def _starter_code() -> dict[str, str]:
    return {
        "Python": (
            "import sys\n\n"
            "def solve():\n"
            "    # Read from standard input and write the required answer.\n"
            "    pass\n\n"
            "if __name__ == '__main__':\n"
            "    solve()\n"
        )
    }


def package_to_problem(raw_files: dict[str, bytes], package_name: str) -> dict[str, Any]:
    files = _load_package_bytes(raw_files)

    try:
        metadata = yaml.safe_load(files["problem.yaml"].decode("utf-8", errors="replace")) or {}
    except yaml.YAMLError as exc:
        raise ProblemPackageError(f"Invalid problem.yaml: {exc}") from exc

    if not isinstance(metadata, dict):
        raise ProblemPackageError("problem.yaml must contain a YAML mapping.")

    title = _localized_value(metadata.get("name")) or package_name
    keywords = metadata.get("keywords") or []
    oj_metadata = _metadata_mapping(metadata.get("oj-lab-metadata"))
    if not keywords:
        keywords = oj_metadata.get("tags") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    topics = [str(item).strip() for item in keywords if str(item).strip()]

    statement, statement_file = _statement_from_files(files)
    statement_title = _extract_statement_title(statement)
    if statement_title and "%s" in title:
        title = statement_title
    title = title.replace("%s", "").strip(" -") or statement_title or package_name
    slug = _slugify(title)
    test_cases = _extract_test_cases(files)

    limits = metadata.get("limits") or {}
    if not isinstance(limits, dict):
        limits = {}

    time_limit = _read_time_limit(files, limits)
    try:
        time_limit_ms = max(100, int(float(time_limit) * 1000))
    except (TypeError, ValueError):
        time_limit_ms = 2000

    memory_limit = limits.get("memory")
    try:
        memory_limit_mb = int(memory_limit) if memory_limit is not None else None
    except (TypeError, ValueError):
        memory_limit_mb = None

    validation = metadata.get("validation", "default")
    problem_validator_flags = _validator_flags(metadata.get("validator_flags"))
    if isinstance(validation, dict):
        validation_name = "custom"
        validation_metadata = validation
    else:
        validation_name = str(validation or "default")
        validation_metadata = validation_name

    problem_type = metadata.get("type", "pass-fail")
    if isinstance(problem_type, list):
        type_values = [str(item) for item in problem_type]
    else:
        type_values = [str(problem_type)]

    samples = [
        {
            "input": case.input_data,
            "output": case.expected_output,
            "name": case.name,
        }
        for case in test_cases
        if case.visibility == "sample"
    ][:8]

    source_name = _source_text(metadata.get("source"))
    if not source_name and "oj-lab-metadata" in metadata:
        source_name = "oj-lab"
    source_name = source_name or "problem-package"
    source_url = metadata.get("source_url")
    external_id = str(metadata.get("uuid") or package_name)

    package_metadata = {
        "problem_format_version": metadata.get("problem_format_version"),
        "author": metadata.get("author"),
        "source": metadata.get("source"),
        "license": metadata.get("license"),
        "rights_owner": metadata.get("rights_owner"),
        "keywords": topics,
        "difficulty": _source_text(oj_metadata.get("difficulty")) or metadata.get("difficulty"),
        "languages": metadata.get("languages"),
        "type": type_values,
        "validation": validation_metadata,
        "validator_flags": problem_validator_flags,
        "statement_file": statement_file,
        "test_case_count": len(test_cases),
        "sample_test_count": sum(case.visibility == "sample" for case in test_cases),
        "secret_test_count": sum(case.visibility == "secret" for case in test_cases),
    }

    has_custom_output_validator = any(
        path.startswith("output_validator/") or path.startswith("output_validators/")
        for path in files
    )
    package_metadata["has_custom_output_validator"] = has_custom_output_validator

    judge_supported = (
        "pass-fail" in type_values
        and validation_name == "default"
        and not has_custom_output_validator
        and "interactive" not in type_values
        and "multi-pass" not in type_values
        and "submit-answer" not in type_values
        and "scoring" not in type_values
    )
    package_metadata["judge_supported"] = judge_supported

    if "domjudge-problem.ini" in files:
        package_metadata["domjudge"] = _parse_domjudge_ini(
            files["domjudge-problem.ini"].decode("utf-8", errors="replace")
        )

    return {
        "slug": slug,
        "title": title[:180],
        "difficulty": (str(oj_metadata.get("difficulty") or metadata.get("difficulty") or "Unknown").title()),
        "topics": topics,
        "description": statement,
        "constraints": [],
        "examples": samples,
        "test_cases": [
            {
                "name": case.name,
                "input": case.input_data,
                "expected_output": case.expected_output,
                "visibility": case.visibility,
                "validator_flags": case.validator_flags or problem_validator_flags,
            }
            for case in test_cases
        ],
        "starter_code": _starter_code(),
        "source": "problem-package" if len(source_name) > 40 else source_name,
        "external_id": external_id[:120],
        "external_url": str(source_url)[:500] if source_url else None,
        "execution_mode": "stdio",
        "time_limit_ms": time_limit_ms,
        "memory_limit_mb": memory_limit_mb,
        "validation": validation_name[:30],
        "package_metadata": package_metadata,
    }


def load_problem_package(path: str) -> dict[str, Any]:
    package = PurePosixPath(path)
    if str(package) != path:
        # The path may contain platform-specific separators; runtime loading below
        # uses the normal filesystem APIs.
        pass

    import pathlib

    filesystem_path = pathlib.Path(path)
    if filesystem_path.is_dir():
        raw_files = {}
        for file_path in filesystem_path.rglob("*"):
            if file_path.is_file():
                raw_files[file_path.relative_to(filesystem_path).as_posix()] = file_path.read_bytes()
        package_name = filesystem_path.name
    elif filesystem_path.is_file() and filesystem_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(filesystem_path, "r") as archive:
            raw_files = {info.filename: archive.read(info) for info in archive.infolist() if not info.is_dir()}
        package_name = filesystem_path.stem
    else:
        raise ProblemPackageError("Input must be a problem package directory or .zip file.")

    return package_to_problem(raw_files, package_name)
