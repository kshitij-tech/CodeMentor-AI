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