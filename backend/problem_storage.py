from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


class ProblemStorageError(ValueError):
    pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_STORAGE_ROOT = PROJECT_ROOT / ".codementor_problem_packages"


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ProblemStorageError(f"Unsafe package path: {name}")
    return path


def _package_root_from_names(names: list[str]) -> PurePosixPath:
    safe = [_safe_member_path(name) for name in names]
    if PurePosixPath("problem.yaml") in safe:
        return PurePosixPath("")

    candidates = [path for path in safe if path.name == "problem.yaml"]
    if not candidates:
        raise ProblemStorageError("Package must contain problem.yaml.")

    return candidates[0].parent


def _copy_directory(source: Path, destination: Path) -> None:
    for item in source.rglob("*"):
        if item.is_symlink():
            raise ProblemStorageError("Symbolic links are not allowed in imported packages.")
        if not item.is_file():
            continue

        relative = item.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def _extract_zip(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source, "r") as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        root = _package_root_from_names(names)

        for info in infos:
            path = _safe_member_path(info.filename)
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue

            if not str(relative):
                continue

            target = destination / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)

            with archive.open(info, "r") as source_stream, open(target, "wb") as target_stream:
                shutil.copyfileobj(source_stream, target_stream)


def materialize_problem_package(path: Path, slug: str) -> str:
    source = path.expanduser().resolve()
    if not source.exists():
        raise ProblemStorageError(f"Package path does not exist: {source}")

    PACKAGE_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    destination = PACKAGE_STORAGE_ROOT / slug

    if source == destination.resolve():
        return destination.relative_to(PROJECT_ROOT).as_posix()

    temp_destination = Path(
        tempfile.mkdtemp(
            prefix=f"{slug}-",
            dir=str(PACKAGE_STORAGE_ROOT),
        )
    )

    try:
        if source.is_dir():
            _copy_directory(source, temp_destination)
        elif source.is_file() and source.suffix.lower() in {".zip", ".kpp"}:
            _extract_zip(source, temp_destination)
        else:
            raise ProblemStorageError("Input must be a problem package directory or .zip/.kpp file.")

        if not (temp_destination / "problem.yaml").is_file():
            raise ProblemStorageError("Materialized package is missing problem.yaml.")

        if destination.exists():
            shutil.rmtree(destination)

        os.replace(temp_destination, destination)
    except Exception:
        shutil.rmtree(temp_destination, ignore_errors=True)
        raise

    return destination.relative_to(PROJECT_ROOT).as_posix()
