from __future__ import annotations

import math
import re
import shlex
from dataclasses import dataclass
from typing import Iterable


_FLOAT_RE = re.compile(
    r"^[+-]?(?:"
    r"\d*\.\d+"
    r"|\d+\."
    r"|\d+"
    r")(?:[Ee][+-]?\d+)?$"
)


class UnsupportedValidatorError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    message: str | None = None


def _argument_tokens(flags: Iterable[str] | str | None) -> list[str]:
    if flags is None:
        return []

    if isinstance(flags, str):
        return shlex.split(flags)

    tokens: list[str] = []
    for flag in flags:
        if not isinstance(flag, str):
            raise UnsupportedValidatorError("Validator arguments must be strings.")
        tokens.extend(shlex.split(flag))
    return tokens


def parse_default_validator_flags(
    flags: Iterable[str] | str | None,
) -> dict[str, float | bool]:
    tokens = _argument_tokens(flags)
    options: dict[str, float | bool] = {
        "case_sensitive": False,
        "space_change_sensitive": False,
    }

    index = 0
    while index < len(tokens):
        token = tokens[index]

        if token in {"case_sensitive", "space_change_sensitive"}:
            options[token] = True
            index += 1
            continue

        if token in {
            "float_tolerance",
            "float_relative_tolerance",
            "float_absolute_tolerance",
        }:
            if index + 1 >= len(tokens):
                raise UnsupportedValidatorError(
                    f"Validator flag '{token}' requires a numeric value."
                )
            try:
                value = float(tokens[index + 1])
            except ValueError as exc:
                raise UnsupportedValidatorError(
                    f"Validator flag '{token}' requires a numeric value."
                ) from exc
            if not math.isfinite(value) or value < 0:
                raise UnsupportedValidatorError(
                    f"Validator flag '{token}' requires a finite non-negative value."
                )
            if token == "float_tolerance":
                if "float_relative_tolerance" in options or "float_absolute_tolerance" in options:
                    raise UnsupportedValidatorError(
                        "float_tolerance cannot be combined with relative/absolute float tolerance."
                    )
                options["float_relative_tolerance"] = value
                options["float_absolute_tolerance"] = value
            else:
                if "float_tolerance" in options:
                    raise UnsupportedValidatorError(
                        "float_tolerance cannot be combined with relative/absolute float tolerance."
                    )
                options[token] = value
            index += 2
            continue

        raise UnsupportedValidatorError(f"Unsupported default validator flag: {token}")

    return options


def _tokens(value: str) -> list[str]:
    return value.split()


def _ascii_casefold(token: str) -> str:
    return token.translate(
        str.maketrans(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "abcdefghijklmnopqrstuvwxyz",
        )
    )


def _float_equal(
    actual: str,
    expected: str,
    *,
    relative_tolerance: float | None,
    absolute_tolerance: float | None,
) -> bool | None:
    if not _FLOAT_RE.fullmatch(expected):
        return None

    if relative_tolerance is None and absolute_tolerance is None:
        return None

    if not _FLOAT_RE.fullmatch(actual):
        return False

    try:
        actual_value = float(actual)
        expected_value = float(expected)
    except ValueError:
        return False

    if not math.isfinite(actual_value) or not math.isfinite(expected_value):
        return actual_value == expected_value

    if absolute_tolerance is not None and abs(actual_value - expected_value) <= absolute_tolerance:
        return True

    if relative_tolerance is not None and abs(actual_value - expected_value) <= (
        relative_tolerance * abs(expected_value)
    ):
        return True

    return False


def validate_default_output(
    actual: str,
    expected: str,
    flags: Iterable[str] | str | None = None,
) -> ValidationResult:
    options = parse_default_validator_flags(flags)

    if options["space_change_sensitive"] and actual != expected:
        # Still report a token-level mismatch below when possible, but reject
        # immediately because whitespace itself is significant in this mode.
        return ValidationResult(
            False,
            "Output whitespace differs from the expected output.",
        )

    actual_tokens = _tokens(actual)
    expected_tokens = _tokens(expected)

    if len(actual_tokens) != len(expected_tokens):
        return ValidationResult(
            False,
            f"Expected {len(expected_tokens)} output tokens, got {len(actual_tokens)}.",
        )

    case_sensitive = bool(options["case_sensitive"])
    relative_tolerance = options.get("float_relative_tolerance")
    absolute_tolerance = options.get("float_absolute_tolerance")

    for position, (actual_token, expected_token) in enumerate(
        zip(actual_tokens, expected_tokens),
        start=1,
    ):
        float_match = _float_equal(
            actual_token,
            expected_token,
            relative_tolerance=relative_tolerance,
            absolute_tolerance=absolute_tolerance,
        )
        if float_match is True:
            continue
        if float_match is False:
            return ValidationResult(
                False,
                f"Output token {position} is outside the allowed floating-point tolerance.",
            )

        if case_sensitive:
            equal = actual_token == expected_token
        else:
            equal = _ascii_casefold(actual_token) == _ascii_casefold(expected_token)

        if not equal:
            return ValidationResult(
                False,
                f"Output token {position} does not match the expected token.",
            )

    return ValidationResult(True, "Output accepted by the default validator.")
