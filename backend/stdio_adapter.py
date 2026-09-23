from __future__ import annotations

import ast
import re
from typing import Any


SCHEMA_TYPES = {
    "int",
    "float",
    "string",
    "raw_string",
    "int_array",
    "float_array",
    "string_array",
}

_LENGTH_NAMES = {"n", "m", "k", "q", "size", "count", "length", "len", "t"}


def normalize_editor_input_schema(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("parameters") or value.get("params") or value.get("schema")
    if not isinstance(value, list):
        return []

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        kind = str(item.get("type") or "").strip().lower()
        if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        if kind not in SCHEMA_TYPES or name in seen:
            continue

        entry = {"name": name, "type": kind}
        if item.get("length_from"):
            entry["length_from"] = str(item["length_from"]).strip()
        result.append(entry)
        seen.add(name)

    return result[:10]


def _value_type(value: Any) -> str:
    if isinstance(value, bool) or isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        if all(isinstance(x, str) for x in value):
            return "string_array"
        if all(isinstance(x, (int, bool)) for x in value):
            return "int_array"
        if all(isinstance(x, (int, float)) for x in value):
            return "float_array"
        return "int_array"
    return "string"


def _assignment_schema(examples: Any) -> list[dict[str, Any]]:
    if not isinstance(examples, list):
        return []

    for example in examples:
        if not isinstance(example, dict):
            continue
        raw = example.get("input")
        if not isinstance(raw, str) or "=" not in raw:
            continue

        schema: list[dict[str, Any]] = []
        for match in re.finditer(
            r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\[[^\]]*\]|[^,]+)",
            raw,
        ):
            name = match.group(1)
            if name.lower() in {"input", "output", "example"}:
                continue

            value_text = match.group(2).strip()
            try:
                parsed = ast.literal_eval(value_text)
            except (SyntaxError, ValueError):
                parsed = value_text
            schema.append({"name": name, "type": _value_type(parsed)})

        if schema:
            length_name = next(
                (
                    item["name"]
                    for item in schema
                    if item["type"] == "int"
                    and item["name"].lower() in _LENGTH_NAMES
                ),
                None,
            )
            for item in schema:
                if item["type"].endswith("_array") and length_name:
                    item["length_from"] = length_name
            return normalize_editor_input_schema(schema)

    return []


def _input_section(description: Any) -> str:
    text = str(description or "")
    match = re.search(
        r"(?is)(?:^|\n)\s*input\s*:?[ \t]*\n?(.*?)(?=\n\s*(?:output|examples?|constraints?)\s*:?)",
        text,
    )
    return match.group(1) if match else text


def infer_editor_input_schema(
    description: Any,
    examples: Any = None,
    explicit_schema: Any = None,
) -> list[dict[str, Any]]:
    explicit = normalize_editor_input_schema(explicit_schema)
    # A persisted raw_string schema is only a fallback. Re-infer from the
    # problem statement so older imported problems can be upgraded without a
    # database migration.
    if explicit and not (
        len(explicit) == 1
        and explicit[0].get("name") == "input_data"
        and explicit[0].get("type") == "raw_string"
    ):
        return explicit

    assignment = _assignment_schema(examples)
    if assignment:
        return assignment

    section = _input_section(description)
    matches: list[tuple[int, str, str]] = []
    seen: set[str] = set()

    patterns = (
        (
            "array",
            r"(?i)\b(?:array|list|sequence)\s+(?:of\s+[A-Za-z]+\s+)?([A-Za-z_][A-Za-z0-9_]*)",
        ),
        (
            "counted_array",
            r"(?i)\b(n|m|k|q|size|count|length|len)\s+integers?\s*[:\-]?\s*"
            r"(?:named\s+)?([A-Za-z_][A-Za-z0-9_]*)(?:_\d+)?",
        ),
        ("string", r"(?i)\b(?:string|word)\s+([A-Za-z_][A-Za-z0-9_]*)"),
        (
            "int",
            r"(?i)\b(?:integer|int|number|value)\s+([A-Za-z_][A-Za-z0-9_]*)",
        ),
    )

    counted_lengths: dict[str, str] = {}
    for kind, pattern in patterns:
        for match in re.finditer(pattern, section):
            if kind == "counted_array":
                length_name, name = match.group(1), match.group(2)
                item_kind = "array"
            else:
                name = match.group(1)
                length_name = None
                item_kind = kind
            if (
                name.lower() in {"the", "a", "an", "input", "output"}
                or name in seen
            ):
                continue
            matches.append((match.start(), name, item_kind))
            seen.add(name)
            if item_kind == "array" and length_name:
                counted_lengths[name] = length_name

    candidates = [
        (name, kind)
        for _, name, kind in sorted(matches, key=lambda item: item[0])
    ]

    if not candidates:
        for name in re.findall(
            r"\b(?:n|m|k|q|x|y|target)\b",
            section,
        ):
            if name not in seen:
                candidates.append((name, "int"))
                seen.add(name)

    schema: list[dict[str, Any]] = []
    length_name = next(
        (
            name
            for name, kind in candidates
            if kind == "int" and name.lower() in _LENGTH_NAMES
        ),
        None,
    )

    for name, kind in candidates:
        if kind == "array":
            item = {"name": name, "type": "int_array"}
            inferred_length = counted_lengths.get(name)
            if inferred_length:
                item["length_from"] = inferred_length
            elif length_name and length_name != name:
                item["length_from"] = length_name
        elif kind == "string":
            item = {"name": name, "type": "string"}
        else:
            item = {"name": name, "type": "int"}
        schema.append(item)

    return normalize_editor_input_schema(schema)


def _schema_consumes_example(
    schema: list[dict[str, Any]],
    raw_input: str,
) -> bool:
    tokens = str(raw_input or "").split()
    if not tokens:
        return False

    values: dict[str, int | float | str] = {}
    index = 0

    for item in schema:
        kind = item["type"]
        name = item["name"]

        if kind == "raw_string":
            return True

        if kind in {"int", "float", "string"}:
            if index >= len(tokens):
                return False
            token = tokens[index]
            index += 1
            try:
                values[name] = (
                    int(token)
                    if kind == "int"
                    else float(token)
                    if kind == "float"
                    else token
                )
            except ValueError:
                return False
            continue

        length_from = item.get("length_from")
        if not length_from:
            return False

        raw_length = values.get(length_from)
        if not isinstance(raw_length, int) or raw_length < 0:
            return False

        index += raw_length
        if index > len(tokens):
            return False

    return index == len(tokens)


def editor_schema_from_metadata(
    package_metadata: Any,
    description: Any,
    examples: Any,
) -> list[dict[str, Any]]:
    metadata = package_metadata if isinstance(package_metadata, dict) else {}

    explicit = normalize_editor_input_schema(
        metadata.get("editor_input_schema") or metadata.get("input_schema"),
    )
    if explicit and not (
        len(explicit) == 1
        and explicit[0].get("name") == "input_data"
        and explicit[0].get("type") == "raw_string"
    ):
        return explicit

    schema = infer_editor_input_schema(
        description,
        examples,
        explicit_schema=explicit,
    )
    raw_examples = [
        str(item.get("input") or "")
        for item in (examples or [])
        if isinstance(item, dict)
        and item.get("input") is not None
        and "=" not in str(item.get("input") or "")
    ]

    # If the statement yielded a concrete schema, keep it for the editor.
    # Some imported examples contain formatting/header text that cannot be
    # validated by the simple token parser; that must not collapse the UX back
    # to solve(string input_data).
    return schema or [{"name": "input_data", "type": "raw_string"}]


def _cpp_type(kind: str) -> str:
    return {
        "int": "long long",
        "float": "double",
        "string": "string",
        "raw_string": "string",
        "int_array": "vector<long long>",
        "float_array": "vector<double>",
        "string_array": "vector<string>",
    }[kind]


def _java_type(kind: str) -> str:
    return {
        "int": "long",
        "float": "double",
        "string": "String",
        "raw_string": "String",
        "int_array": "long[]",
        "float_array": "double[]",
        "string_array": "String[]",
    }[kind]


def _go_type(kind: str) -> str:
    return {
        "int": "int64",
        "float": "float64",
        "string": "string",
        "raw_string": "string",
        "int_array": "[]int64",
        "float_array": "[]float64",
        "string_array": "[]string",
    }[kind]


def _rust_type(kind: str) -> str:
    return {
        "int": "i64",
        "float": "f64",
        "string": "String",
        "raw_string": "String",
        "int_array": "Vec<i64>",
        "float_array": "Vec<f64>",
        "string_array": "Vec<String>",
    }[kind]


def generate_stdio_editor_starters(schema: Any) -> dict[str, str]:
    schema = normalize_editor_input_schema(schema)
    if not schema:
        return {}

    names = [item["name"] for item in schema]
    cpp = ", ".join(
        f"{_cpp_type(item['type'])} {item['name']}"
        for item in schema
    )
    java = ", ".join(
        f"{_java_type(item['type'])} {item['name']}"
        for item in schema
    )
    go = ", ".join(
        f"{item['name']} {_go_type(item['type'])}"
        for item in schema
    )
    rust = ", ".join(
        f"{item['name']}: {_rust_type(item['type'])}"
        for item in schema
    )

    return {
        "Python": (
            f"def solve({', '.join(names)}):\n"
            "    # Implement the required solution.\n"
            "    pass\n"
        ),
        "C++": (
            "#include <bits/stdc++.h>\n"
            "using namespace std;\n\n"
            f"auto solve({cpp}) {{\n"
            "    // Implement the required solution.\n"
            "    return 0;\n"
            "}\n"
        ),
        "Java": (
            "class Solution {\n"
            f"    public Object solve({java}) {{\n"
            "        // Implement the required solution.\n"
            "        return 0;\n"
            "    }\n"
            "}\n"
        ),
        "JavaScript": (
            f"function solve({', '.join(names)}) {{\n"
            "    // Implement the required solution.\n"
            "    return 0;\n"
            "}\n"
        ),
        "TypeScript": (
            f"function solve({', '.join(item['name'] + ': ' + ('number' if item['type'] in {'int', 'float'} else 'any') for item in schema)}): any {{\n"
            "    // Implement the required solution.\n"
            "    return 0;\n"
            "}\n"
        ),
        "Go": (
            "package main\n\n"
            f"func solve({go}) any {{\n"
            "    // Implement the required solution.\n"
            "    return int64(0)\n"
            "}\n"
        ),
        "Rust": (
            f"fn solve({rust}) -> String {{\n"
            "    // Implement the required solution and return the required output.\n"
            "    String::new()\n"
            "}\n"
        ),
    }


def _python_reader(item: dict[str, Any]) -> str:
    name, kind = item["name"], item["type"]
    if kind == "int":
        return f"    {name} = int(__cm_take())"
    if kind == "float":
        return f"    {name} = float(__cm_take())"
    if kind == "string":
        return f"    {name} = __cm_take()"
    if kind == "raw_string":
        return f"    {name} = __cm_raw_input"

    length = item.get("length_from")
    if kind.endswith("_array") and length:
        parse = {
            "int_array": "int64",
            "float_array": "float",
            "string_array": "str",
        }[kind]
        return (
            f"    {name} = "
            f"[{parse}(__cm_take()) for _ in range(int({length}))]"
        )

    raise ValueError(f"Unsupported or underspecified schema type: {kind}")


def _render_python_adapter(
    source: str,
    schema: list[dict[str, Any]],
) -> str:
    lines = [
        "import sys",
        "",
        source.rstrip(),
        "",
        "__cm_raw_input = sys.stdin.read()",
        "__cm_tokens = __cm_raw_input.split()",
        "__cm_index = 0",
        "def __cm_take():",
        "    global __cm_index",
        "    if __cm_index >= len(__cm_tokens):",
        "        raise ValueError('Insufficient input for the problem schema.')",
        "    value = __cm_tokens[__cm_index]",
        "    __cm_index += 1",
        "    return value",
        "",
        "def __cm_parse_input():",
    ]
    lines.extend(_python_reader(item) for item in schema)
    lines += [
        "    return [" + ", ".join(item["name"] for item in schema) + "]",
        "",
        "__cm_result = solve(*__cm_parse_input())",
        "if isinstance(__cm_result, (list, tuple)):",
        "    if __cm_result and isinstance(__cm_result[0], (list, tuple)):",
        "        print('\\n'.join(' '.join(map(str, row)) for row in __cm_result))",
        "    else:",
        "        print(' '.join(map(str, __cm_result)))",
        "else:",
        "    print('' if __cm_result is None else __cm_result)",
        "",
    ]
    return "\n".join(lines)


def _cpp_reader(item: dict[str, Any]) -> str:
    name, kind = item["name"], item["type"]
    if kind == "int":
        return f"    long long {name}; cin >> {name};"
    if kind == "float":
        return f"    double {name}; cin >> {name};"
    if kind == "string":
        return f"    string {name}; cin >> {name};"
    if kind == "raw_string":
        return (
            f"    string {name}((istreambuf_iterator<char>(cin)), "
            "istreambuf_iterator<char>());"
        )

    length = item.get("length_from")
    if kind.endswith("_array") and length:
        typ = {
            "int_array": "long long",
            "float_array": "double",
            "string_array": "string",
        }[kind]
        return (
            f"    vector<{typ}> {name}({length}); "
            f"for (auto &v : {name}) cin >> v;"
        )

    raise ValueError(f"Unsupported or underspecified schema type: {kind}")


def _render_cpp_adapter(
    source: str,
    schema: list[dict[str, Any]],
) -> str:
    args = ", ".join(item["name"] for item in schema)
    lines = [
        "#include <bits/stdc++.h>",
        "using namespace std;",
        "",
        source.rstrip(),
        "",
        "template <typename T> void __cm_print(const T& value) { cout << value; }",
        "template <typename T> void __cm_print(const vector<T>& value) {",
        "    for (size_t i = 0; i < value.size(); ++i) {",
        "        if (i) cout << ' ';",
        "        __cm_print(value[i]);",
        "    }",
        "}",
        "",
        "int main() {",
        "    ios::sync_with_stdio(false);",
        "    cin.tie(nullptr);",
    ]
    lines.extend(_cpp_reader(item) for item in schema)
    lines += [
        f"    auto __cm_result = solve({args});",
        "    __cm_print(__cm_result);",
        "    cout << '\\n';",
        "    return 0;",
        "}",
        "",
    ]
    return "\n".join(lines)


def _java_reader(item: dict[str, Any]) -> str:
    name, kind = item["name"], item["type"]
    if kind == "int":
        return f"        long {name} = __cm.nextLong();"
    if kind == "float":
        return f"        double {name} = __cm.nextDouble();"
    if kind == "string":
        return f"        String {name} = __cm.next();"
    if kind == "raw_string":
        return f"        String {name} = __cm.readAll();"

    length = item.get("length_from")
    if kind.endswith("_array") and length:
        if kind == "int_array":
            return (
                f"        long[] {name} = new long[(int){length}]; "
                f"for (int i=0;i<{name}.length;i++) {name}[i]=__cm.nextLong();"
            )
        if kind == "float_array":
            return (
                f"        double[] {name} = new double[(int){length}]; "
                f"for (int i=0;i<{name}.length;i++) {name}[i]=__cm.nextDouble();"
            )
        return (
            f"        String[] {name} = new String[(int){length}]; "
            f"for (int i=0;i<{name}.length;i++) {name}[i]=__cm.next();"
        )

    raise ValueError(f"Unsupported or underspecified schema type: {kind}")


def _render_java_adapter(
    source: str,
    schema: list[dict[str, Any]],
) -> str:
    args = ", ".join(item["name"] for item in schema)
    parse_lines = "\n".join(_java_reader(item) for item in schema)
    return (
        source.rstrip()
        + "\n\npublic class Main {\n"
        + "    static final class Input {\n"
        + "        private final java.io.BufferedInputStream in = new java.io.BufferedInputStream(System.in);\n"
        + "        private final byte[] buffer = new byte[1 << 16];\n"
        + "        private int ptr = 0, len = 0;\n"
        + "        private int read() throws java.io.IOException { if (ptr >= len) { len = in.read(buffer); ptr = 0; if (len < 0) return -1; } return buffer[ptr++]; }\n"
        + "        String next() throws java.io.IOException { StringBuilder b=new StringBuilder(); int c; do { c=read(); } while(c<=32 && c!=-1); while(c>32){ b.append((char)c); c=read(); } return b.toString(); }\n"
        + "        long nextLong() throws java.io.IOException { return Long.parseLong(next()); }\n"
        + "        double nextDouble() throws java.io.IOException { return Double.parseDouble(next()); }\n"
        + "        String readAll() throws java.io.IOException { StringBuilder b=new StringBuilder(); byte[] buf=new byte[1<<16]; int n; while((n=in.read(buf))!=-1){ b.append(new String(buf,0,n,java.nio.charset.StandardCharsets.UTF_8)); } return b.toString(); }\n"
        + "    }\n"
        + "    static String format(Object v) { if(v==null)return \"\"; if(!v.getClass().isArray())return String.valueOf(v); int n=java.lang.reflect.Array.getLength(v); StringBuilder b=new StringBuilder(); for(int i=0;i<n;i++){ if(i>0)b.append(' '); b.append(format(java.lang.reflect.Array.get(v,i))); } return b.toString(); }\n"
        + "    public static void main(String[] args) throws Exception {\n"
        + "        Input __cm = new Input();\n"
        + parse_lines
        + "\n        Object __cmResult = new Solution().solve(" + args + ");\n"
        + "        System.out.println(format(__cmResult));\n"
        + "    }\n"
        + "}\n"
    )


def _js_reader(item: dict[str, Any]) -> str:
    name, kind = item["name"], item["type"]
    if kind in {"int", "float"}:
        return f"const {name}=Number(__cmTake());"
    if kind == "string":
        return f"const {name}=__cmTake();"
    if kind == "raw_string":
        return f"const {name}=__cmRawInput;"

    length = item.get("length_from")
    if kind.endswith("_array") and length:
        mapper = {
            "int_array": "Number",
            "float_array": "Number",
            "string_array": "String",
        }[kind]
        return (
            f"const {name}=Array.from("
            f"{{length:Number({length})}},"
            f"()=>{mapper}(__cmTake())"
            ");"
        )

    raise ValueError(f"Unsupported or underspecified schema type: {kind}")


def _render_javascript_adapter(
    source: str,
    schema: list[dict[str, Any]],
) -> str:
    args = ", ".join(item["name"] for item in schema)
    parsed = "\n".join(_js_reader(item) for item in schema)
    helper = r"""const __cmFs = require('fs');
const __cmRawInput = __cmFs.readFileSync(0, 'utf8');
const __cmTokens = __cmRawInput.trim().split(/\s+/).filter(Boolean);
let __cmIndex = 0;
const __cmTake = () => {
  if (__cmIndex >= __cmTokens.length) {
    throw new Error('Insufficient input for the problem schema.');
  }
  return __cmTokens[__cmIndex++];
};
const __cmFormat = value => {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) {
    return value.length && Array.isArray(value[0])
      ? value.map(__cmFormat).join('\\n')
      : value.map(__cmFormat).join(' ');
  }
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};
"""
    return (
        source.rstrip()
        + "\n\n"
        + helper
        + parsed
        + f"\nprocess.stdout.write(__cmFormat(solve({args})) + '\\n');\n"
    )


def _go_import_specs(source: str) -> list[str]:
    specs: list[str] = []

    block = re.search(
        r"(?ms)^\s*import\s*\((.*?)^\)\s*",
        source,
    )
    if block:
        specs.extend(
            line.strip()
            for line in block.group(1).splitlines()
            if line.strip() and not line.strip().startswith("//")
        )

    specs.extend(
        line.strip()
        for line in re.findall(
            r'(?m)^\s*import\s+([^\n]+)$',
            source,
        )
        if line.strip()
    )
    return specs


def _render_go_adapter(
    source: str,
    schema: list[dict[str, Any]],
) -> str:
    user_imports = _go_import_specs(source)
    body = source.rstrip()
    body = re.sub(r"(?m)^\s*package\s+main\s*\n", "", body, count=1)
    body = re.sub(r"(?ms)^\s*import\s*\(.*?^\)\s*\n?", "", body, count=1)
    body = re.sub(r'(?m)^\s*import\s+"[^"]+"\s*\n?', "", body, count=1)

    required = ['"bufio"', '"fmt"', '"os"', '"reflect"', '"strings"']
    if any(item["type"] == "raw_string" for item in schema):
        required.append('"io"')

    merged: list[str] = []
    seen: set[str] = set()
    for spec in required + user_imports:
        match = re.search(r'"([^"]+)"', spec)
        key = match.group(1) if match else spec
        if key in seen:
            continue
        seen.add(key)
        merged.append(spec)

    args = ", ".join(item["name"] for item in schema)
    lines = [
        "package main",
        "",
        "import (",
        *[f"    {spec}" for spec in merged],
        ")",
        "",
        body.strip(),
        "",
        "func __cmFormat(value any) string {",
        "    if value == nil { return \"\" }",
        "    rv := reflect.ValueOf(value)",
        "    if rv.Kind() == reflect.Slice || rv.Kind() == reflect.Array {",
        "        parts := make([]string, rv.Len())",
        "        for i := 0; i < rv.Len(); i++ { parts[i] = __cmFormat(rv.Index(i).Interface()) }",
        "        return strings.Join(parts, \" \")",
        "    }",
        "    return fmt.Sprint(value)",
        "}",
        "",
        "func main() {",
        "    reader := bufio.NewReader(os.Stdin)",
    ]
    lines.extend(_go_reader(item) for item in schema)
    lines += [
        f"    __cmResult := solve({args})",
        "    fmt.Println(__cmFormat(__cmResult))",
        "}",
        "",
    ]
    return "\n".join(lines)


def _go_reader(item: dict[str, Any]) -> str:
    name, kind = item["name"], item["type"]
    if kind == "int":
        return (
            f"    var {name} int64; "
            f"if _, err := fmt.Fscan(reader, &{name}); err != nil {{ panic(err) }}"
        )
    if kind == "float":
        return (
            f"    var {name} float64; "
            f"if _, err := fmt.Fscan(reader, &{name}); err != nil {{ panic(err) }}"
        )
    if kind == "string":
        return (
            f"    var {name} string; "
            f"if _, err := fmt.Fscan(reader, &{name}); err != nil {{ panic(err) }}"
        )
    if kind == "raw_string":
        return (
            f"    {name}Bytes, err := io.ReadAll(reader); "
            f"if err != nil {{ panic(err) }}; "
            f"{name} := string({name}Bytes)"
        )

    length = item.get("length_from")
    if kind.endswith("_array") and length:
        typ = {
            "int_array": "int64",
            "float_array": "float64",
            "string_array": "string",
        }[kind]
        return (
            f"    {name} := make([]{typ}, int({length})); "
            f"for i := range {name} {{ "
            f"if _, err := fmt.Fscan(reader, &{name}[i]); err != nil {{ panic(err) }} }}"
        )

    raise ValueError(f"Unsupported or underspecified schema type: {kind}")


def _render_rust_adapter(
    source: str,
    schema: list[dict[str, Any]],
) -> str:
    args = ", ".join(item["name"] for item in schema)
    lines = [
        source.rstrip(),
        "",
        "fn main() {",
        "    let mut __cm_input = String::new();",
        "    std::io::Read::read_to_string(&mut std::io::stdin(), &mut __cm_input).unwrap();",
        "    let mut __cm_it = __cm_input.split_whitespace();",
    ]

    for item in schema:
        name, kind = item["name"], item["type"]
        if kind == "int":
            lines.append(
                f"    let {name}: i64 = __cm_it.next().unwrap().parse().unwrap();"
            )
        elif kind == "float":
            lines.append(
                f"    let {name}: f64 = __cm_it.next().unwrap().parse().unwrap();"
            )
        elif kind == "string":
            lines.append(
                f'    let {name}: String = __cm_it.next().unwrap().to_string();'
            )
        elif kind == "raw_string":
            lines.append(
                f"    let {name}: String = __cm_input.clone();"
            )
        elif kind.endswith("_array") and item.get("length_from"):
            base = {
                "int_array": "i64",
                "float_array": "f64",
                "string_array": "String",
            }[kind]
            lines.append(
                f"    let {name}: Vec<{base}> = "
                f"(0..({item['length_from']} as usize))"
                f".map(|_| __cm_it.next().unwrap().parse().unwrap())"
                ".collect();"
            )
        else:
            raise ValueError(f"Unsupported or underspecified schema type: {kind}")

    lines += [
        f"    let __cm_result = solve({args});",
        '    print!("{}\\n", __cm_result);',
        "}",
        "",
    ]
    return "\n".join(lines)


def adapt_stdio_source(
    user_source: str,
    language: str,
    schema: Any,
) -> str:
    normalized = normalize_editor_input_schema(schema)
    if not normalized:
        return user_source

    if language == "Python":
        if re.search(r"(?m)^\s*if\s+__name__\s*==", user_source):
            raise ValueError(
                "Implement solve(...) only. CodeMentor supplies the Standard Input/Output wrapper."
            )
        if re.search(r"\binput\s*\(", user_source):
            raise ValueError(
                "Do not read stdin directly. CodeMentor passes the parsed test-case values to solve(...)."
            )
        return _render_python_adapter(user_source, normalized)

    entrypoints = {
        "C++": r"\b(?:int|signed)\s+main\s*\(",
        "Java": r"\bstatic\s+void\s+main\s*\(",
        "JavaScript": r"\bprocess\.stdout\.write\s*\(",
        "TypeScript": r"\bprocess\.stdout\.write\s*\(",
        "Go": r"(?m)^\s*func\s+main\s*\(",
        "Rust": r"(?m)^\s*fn\s+main\s*\(",
    }
    if re.search(entrypoints.get(language, r"$^"), user_source):
        raise ValueError(
            "Implement solve(...) only. CodeMentor supplies the program entry point."
        )

    if language == "C++":
        return _render_cpp_adapter(user_source, normalized)
    if language == "Java":
        return _render_java_adapter(user_source, normalized)
    if language == "JavaScript":
        return _render_javascript_adapter(user_source, normalized)
    if language == "TypeScript":
        return _render_javascript_adapter(user_source, normalized)
    if language == "Go":
        return _render_go_adapter(user_source, normalized)
    if language == "Rust":
        return _render_rust_adapter(user_source, normalized)

    raise ValueError(f"Unsupported language: {language}.")
