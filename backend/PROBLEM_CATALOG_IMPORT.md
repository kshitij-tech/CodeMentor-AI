# Problem Catalog Import

CodeMentor supports two catalog import paths.

## 1. CodeMentor JSON catalog

Use this for original or licensed content that has already been normalized to CodeMentor's schema.

From the project root:

    python -m backend.import_problems path/to/catalog.json

## 2. ICPC/Kattis-compatible problem packages

This is the preferred format for bulk competitive-programming content. The importer accepts either an extracted package directory or a .zip archive.

    python -m backend.import_problem_package path/to/problem.zip

A package is expected to contain problem.yaml and test data under data/sample/ and/or data/secret/, using matching .in and .ans files.

CodeMentor currently imports problem metadata, a readable statement, sample and secret test cases, time and memory limits, and whether the package is currently judgeable by the local runner.

Imported package problems use standard-input/standard-output execution. Python support is enabled in this stage.

## Validator support in this stage

The local runner currently supports pass/fail problems using the default output validator. Packages using custom validators, interactive problems, scoring problems, multi-pass problems, or submit-answer problems are imported as catalog entries but are marked unsupported for local judging until their judge behavior is implemented.

This is deliberate: the problem-package format supports custom validators and advanced judging modes, so CodeMentor does not silently reduce those problems to a simple string comparison.

For default judging, CodeMentor currently compares normalized whitespace-separated output tokens. A full validator subsystem will replace this in a later stage.

## Security

Package archives are checked for unsafe paths before files are read.

Do not populate this catalog by crawling, scraping, or spidering sites whose terms prohibit those activities. Use content you are authorized to store and redistribute.
## Built-in compatibility fixture

A small public MIT-licensed compatibility fixture is included at:

    backend/problem_fixtures/hello-world

From the project root, import it directly with:

    python -m backend.import_problem_package backend/problem_fixtures/hello-world

This fixture is derived from the `hello-world` package in the public `oj-lab/problem-packages` repository. Its source and license notice are retained in the fixture directory.


## Default output validator

For packages using the default validator, CodeMentor now supports the standard token-based behavior:

- output is tokenized by whitespace by default
- ASCII letter case is ignored unless `case_sensitive` is supplied
- `space_change_sensitive` makes whitespace differences significant
- `float_tolerance ε` applies ε as both relative and absolute tolerance
- `float_relative_tolerance ε` and `float_absolute_tolerance ε` can be supplied separately

Validator flags can come from the package's `validator_flags` (legacy format) or `output_validator_args` in `test_group.yaml`. These semantics follow the ICPC default output-validator specification. citeturn681946search0turn137182search3


## Test-data groups and custom validators

CodeMentor reads `testdata.yaml` from `data/`, `data/sample/`, `data/secret/`, and nested groups. Settings are inherited from parent groups.

For custom pass-fail validators, the importer supports Python validators, prebuilt executables, Windows batch/cmd validators, and single-file C++ validators when `g++` is available. The validator is invoked with the input file, answer file, feedback directory, configured arguments, and the contestant output on stdin. Exit code 42 means Accepted and 43 means Wrong Answer; other exit codes are reported as Judge Error. This matches the Kattis/ICPC output-validator contract. citeturn330198view0turn948456search0

The local validator runner is intended for development. Production execution still needs the stronger OS/container isolation that a system such as DOMjudge provides for contestant and validator processes. citeturn948456search0turn281698search4

## Import the complete OJ Lab package collection

The repository currently contains 14 problem packages under `problems/`. Because the source repository is MIT-licensed, CodeMentor includes a one-shot synchronizer for that complete collection. citeturn933651search0turn601754view0

From the project root:

    python -m backend.sync_ojlab_problem_packages

The command downloads the current `oj-lab/problem-packages` archive, discovers every directory containing `problem.yaml`, and imports them all. Imported package files are persisted in the local `.codementor_problem_packages/` directory and are not committed to Git.

The command prints progress for each package and returns a non-zero exit code if any package failed to import.
