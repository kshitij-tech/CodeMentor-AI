from __future__ import annotations

import html
import re
import shlex
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
    validator_name: str | None
    validator_flags: list[str]
    group: str


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
    value = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", "", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return html.unescape(re.sub(r"[ \\t]+", " ", value)).strip()


def _strip_latex(value: str) -> str:
    value = re.sub(r"(?m)^\\s*%.*$", "", value)
    value = re.sub(r"\\\\(?:begin|end)\\{[^}]+\\}", "\\n", value)
    value = re.sub(r"\\\\(?:textbf|textit|emph|underline|textrm)\\{([^{}]*)\\}", r"\\1", value)
    value = re.sub(r"\\\\(?:section|subsection|subsubsection)\\*?\\{([^{}]*)\\}", r"\\n\\1\\n", value)
    value = re.sub(r"\\\\(?:paragraph)\\*?\\{([^{}]*)\\}", r"\\n\\1\\n", value)
    value = re.sub(r"\\\\[a-zA-Z]+(?:\\[[^\\]]*\\])?\\s*", "", value)
    value = value.replace("~", " ")
    value = re.sub(r"\\n{3,}", "\\n\\n", value)
    return value.strip()


def _metadata_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _extract_statement_title(statement: str) -> str | None:
    match = re.search(r"(?m)^#\\s+(.+?)\\s*$", statement)
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


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff]", value))


def _statement_from_files(files: dict[str, bytes]) -> tuple[str, str | None]:
    # Prefer explicitly English statements when a package provides them.
    preferred = [
        path for path in files
        if path.startswith("problem_statement/")
        and path.lower().endswith((".en.md", ".en.html", ".en.txt", ".en.tex"))
    ]
    preferred.sort()

    candidates = preferred + sorted(
        path for path in files
        if path.startswith("problem_statement/")
        and path.endswith((".md", ".html", ".txt", ".tex"))
        and path not in preferred
    )

    for path in candidates:
        raw = files[path].decode("utf-8", errors="replace")
        if path.endswith(".html"):
            raw = _strip_html(raw)
        elif path.endswith(".tex"):
            raw = _strip_latex(raw)

        raw = raw.strip()
        if not raw:
            continue

        # CodeMentor AI currently imports English-only problem statements.
        # CJK-heavy statements are skipped rather than translated.
        if _contains_cjk(raw):
            continue

        return raw, path

    # Keep legacy top-level statements as a fallback, but apply the same
    # language filter.
    for candidate in ("problem.html", "problem.md", "problem.txt"):
        if candidate not in files:
            continue
        raw = files[candidate].decode("utf-8", errors="replace")
        raw = _strip_html(raw) if candidate.endswith(".html") else raw.strip()
        if raw and not _contains_cjk(raw):
            return raw, candidate

    raise ProblemPackageError("No English problem statement was found.")


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


def _validator_flags(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return _validator_flags(value.get("flags"))
    return []


def _validator_programs(files: dict[str, bytes]) -> dict[str, str]:
    programs: dict[str, str] = {}

    for root_name in ("output_validator", "output_validators"):
        if root_name in files:
            programs[root_name] = root_name

        prefix = root_name + "/"
        for path in files:
            if path.startswith(prefix):
                relative = path[len(prefix):]
                name = relative.split("/", 1)[0]
                programs.setdefault(
                    name if root_name == "output_validators" else root_name,
                    prefix + name if "/" in relative else prefix + relative,
                )

    return programs


def _group_config(files: dict[str, bytes], input_path: str) -> dict[str, Any]:
    path = PurePosixPath(input_path)
    parent = path.parent
    parts = parent.parts

    ancestors: list[str] = ["data"]
    for index in range(2, len(parts) + 1):
        ancestors.append("/".join(parts[:index]))

    merged: dict[str, Any] = {}
    for group in ancestors:
        config_path = f"{group}/testdata.yaml"
        raw = files.get(config_path)
        if raw is None:
            continue
        try:
            config = yaml.safe_load(raw.decode("utf-8", errors="replace")) or {}
        except yaml.YAMLError as exc:
            raise ProblemPackageError(f"Invalid YAML in {config_path}: {exc}") from exc
        if not isinstance(config, dict):
            raise ProblemPackageError(f"{config_path} must contain a YAML mapping.")
        merged.update(config)

    return merged


def _select_validator(
    config: dict[str, Any],
    *,
    root_validator_name: str | None,
    root_flags: list[str],
    available_names: set[str],
) -> tuple[str | None, list[str]]:
    raw = config.get("output_validator_flags")
    if raw is None:
        raw = config.get("output_validator_args")

    if raw is None or raw == "":
        return root_validator_name, list(root_flags)

    if isinstance(raw, dict):
        name = raw.get("name")
        flags = _validator_flags(raw.get("flags"))
        return (str(name) if name else root_validator_name), flags

    if isinstance(raw, list):
        return root_validator_name, _validator_flags(raw)

    if isinstance(raw, str):
        tokens = shlex.split(raw)
        if len(tokens) == 1 and tokens[0] in available_names:
            return tokens[0], []
        return root_validator_name, tokens

    return root_validator_name, list(root_flags)


def _supported_validator_program(path: str, files: dict[str, bytes]) -> bool:
    normalized = path.rstrip("/")
    if normalized in files:
        suffix = PurePosixPath(normalized).suffix.lower()
        return suffix in {".py", ".py3", ".exe", ".cmd", ".bat", ".sh", ".cpp", ".cc", ".cxx"} or suffix == ""

    prefix = normalized + "/"
    package_files = [p for p in files if p.startswith(prefix)]
    if any(p == prefix + "run" for p in package_files):
        return True
    if any(PurePosixPath(p).suffix.lower() in {".py", ".py3", ".cpp", ".cc", ".cxx"} for p in package_files):
        return True
    return False


def _extract_test_cases(
    files: dict[str, bytes],
    *,
    root_validator_name: str | None,
    root_flags: list[str],
    available_validator_names: set[str],
) -> list[PackageTestCase]:
    test_cases: list[PackageTestCase] = []

    for path, data in sorted(files.items()):
        if not path.startswith("data/") or not path.endswith(".in"):
            continue

        relative = PurePosixPath(path)
        if len(relative.parts) < 3 or relative.parts[1] not in {"sample", "secret"}:
            continue

        answer_path = path[:-3] + ".ans"
        if answer_path not in files:
            raise ProblemPackageError(f"Missing answer file for test case: {path}")

        config = _group_config(files, path)
        validator_name, validator_flags = _select_validator(
            config,
            root_validator_name=root_validator_name,
            root_flags=root_flags,
            available_names=available_validator_names,
        )

        group = "/".join(relative.parts[1:-1])
        test_cases.append(
            PackageTestCase(
                name=path[5:-3],
                input_data=data.decode("utf-8", errors="replace"),
                expected_output=files[answer_path].decode("utf-8", errors="replace"),
                visibility=relative.parts[1],
                validator_name=validator_name,
                validator_flags=validator_flags,
                group=group,
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
    files = _find_rooted_files(raw_files)

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
    validation_text = str(validation or "default")
    validation_tokens = validation_text.split()
    validation_kind = validation_tokens[0] if validation_tokens else "default"
    root_validator_name = None
    root_flags = _validator_flags(metadata.get("validator_flags"))
    if not root_flags:
        root_flags = _validator_flags(metadata.get("output_validator_args"))

    problem_type = metadata.get("type", "pass-fail")
    if isinstance(problem_type, list):
        type_values = [str(item) for item in problem_type]
    else:
        type_values = str(problem_type).split()

    available_programs = _validator_programs(files)
    available_names = set(available_programs)

    if validation_kind == "custom":
        if available_names:
            root_validator_name = "output_validator" if "output_validator" in available_names else next(iter(available_names))
    else:
        validation_kind = "default"

    test_cases = _extract_test_cases(
        files,
        root_validator_name=root_validator_name,
        root_flags=root_flags,
        available_validator_names=available_names,
    )

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

    validation_time = limits.get("validation_time", 60)
    validation_output = limits.get("validation_output", 8)
    try:
        validation_time_ms = max(100, int(float(validation_time) * 1000))
    except (TypeError, ValueError):
        validation_time_ms = 60_000
    try:
        validation_output_bytes = max(1024, int(float(validation_output) * 1024 * 1024))
    except (TypeError, ValueError):
        validation_output_bytes = 8 * 1024 * 1024

    custom_validator_programs = {
        name: path
        for name, path in available_programs.items()
        if _supported_validator_program(path, files)
    }

    has_custom_validator = validation_kind == "custom" or bool(available_programs)
    custom_validator_supported = (
        bool(root_validator_name)
        and root_validator_name in custom_validator_programs
        and "interactive" not in validation_tokens
    )

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
        "validation": validation_text,
        "validator_flags": root_flags,
        "validator_programs": available_programs,
        "supported_validator_programs": custom_validator_programs,
        "statement_file": statement_file,
        "test_case_count": len(test_cases),
        "sample_test_count": sum(case.visibility == "sample" for case in test_cases),
        "secret_test_count": sum(case.visibility == "secret" for case in test_cases),
        "validation_time_ms": validation_time_ms,
        "validation_output_bytes": validation_output_bytes,
        "has_custom_output_validator": has_custom_validator,
        "custom_validator_supported": custom_validator_supported,
    }

    if "domjudge-problem.ini" in files:
        package_metadata["domjudge"] = _parse_domjudge_ini(
            files["domjudge-problem.ini"].decode("utf-8", errors="replace")
        )

    pass_fail = "pass-fail" in type_values
    unsupported_type = any(
        item in validation_tokens
        for item in {"interactive", "multi-pass", "submit-answer", "score"}
    )
    case_validator_supported = all(
        not case.validator_name
        or case.validator_name in custom_validator_programs
        for case in test_cases
    )
    uses_custom_validators = any(item.validator_name for item in test_cases)
    judge_supported = (
        pass_fail
        and not unsupported_type
        and case_validator_supported
        and (
            uses_custom_validators
            or validation_kind == "custom"
            and custom_validator_supported
            or validation_kind == "default"
        )
    )
    package_metadata["judge_supported"] = judge_supported

    return {
        "slug": slug,
        "title": title[:180],
        "difficulty": str(oj_metadata.get("difficulty") or metadata.get("difficulty") or "Unknown").title(),
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
                "validator_name": case.validator_name,
                "validator_flags": case.validator_flags,
                "group": case.group,
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
        "validation": validation_text[:30],
        "package_metadata": package_metadata,
    }


def load_problem_package(path: str) -> dict[str, Any]:
    from pathlib import Path

    filesystem_path = Path(path)
    if filesystem_path.is_dir():
        raw_files = {}
        for file_path in filesystem_path.rglob("*"):
            if file_path.is_file():
                relative = file_path.relative_to(filesystem_path).as_posix()
                raw_files[relative] = file_path.read_bytes()
        package_name = filesystem_path.name
    elif filesystem_path.is_file() and filesystem_path.suffix.lower() in {".zip", ".kpp"}:
        with zipfile.ZipFile(filesystem_path, "r") as archive:
            raw_files = {
                info.filename: archive.read(info)
                for info in archive.infolist()
                if not info.is_dir()
            }
        package_name = filesystem_path.stem
    else:
        raise ProblemPackageError("Input must be a problem package directory or .zip file.")

    return package_to_problem(raw_files, package_name)
