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

## Bulk English problem catalog: DeepMind CodeContests

For a larger English-language catalog, CodeMentor includes a streaming importer for the DeepMind CodeContests dataset. The dataset contains competitive-programming problems with paired public, private, and generated input/output tests. Its dataset card identifies the dataset license as CC BY 4.0 and notes that third-party source terms may also apply, so attribution and source-specific restrictions must be preserved when redistributing content. citeturn505255search0turn865062view0

Install the optional importer dependency:

    pip install -r backend/requirements-problem-import.txt

Then import the training catalog:

    python -m backend.sync_code_contests

The importer streams the dataset instead of loading the full corpus into memory and commits small batches suitable for the default SQLite development database. It keeps English descriptions, skips CJK-heavy or file-based-I/O problems, stores public tests as samples, and stores private/generated tests as hidden tests. By default it stores up to 10 hidden tests per problem; use `--max-secret-tests 0` to retain all available hidden tests. The importer also caps public tests at 8.

Useful options:

    python -m backend.sync_code_contests --max-problems 100
    python -m backend.sync_code_contests --split valid
    python -m backend.sync_code_contests --max-secret-tests 0

The published dataset metadata lists 13,328 training examples, 117 validation examples, and 165 test examples. citeturn657724search0turn657724search5

The existing `backend/sync_ojlab_problem_packages.py` remains available as a small MIT-licensed package-format compatibility source; packages without an English statement are skipped.
