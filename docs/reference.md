# Python API reference

This is the complete, automatically generated Python API reference for `omnist`, generated directly from codebase docstrings using `mkdocstrings`.

Looking for a conceptual introduction and summary tables? See the [API overview](api.md).

---

## Public Surface (`omnist`)

::: omnist
    options:
      show_root_heading: false
      members:
        - Doc
        - doc
        - Schema
        - Record
        - Scalar
        - Ref
        - Field
        - ValidationResult
        - Error
        - AnyType
        - record
        - ref
        - field
        - schema
        - nullable
        - t
        - STRING
        - INTEGER
        - NUMBER
        - BOOLEAN
        - DATE
        - TIME
        - DATETIME
        - parse_schema
        - to_osd
        - infer
        - infer_with_report
        - AnyFallback
        - materialize
        - lint
        - LintFinding
        - read_json
        - write_json
        - read_yaml
        - write_yaml
        - read_toml
        - write_toml
        - read_xml
        - write_xml
        - read_oml
        - write_oml
        - check_json
        - check_yaml
        - check_toml
        - check_xml
        - check_oml
        - WriteReport
        - Adjustment
        - finish_write
        - Format
        - register_format
        - get_format
        - formats
        - OmnistError
        - SchemaError
        - ParseError
        - WriteError
        - DocumentError
        - DetachedNode
        - UnsafeXMLWarning

---

## Document Model (`omnist.document`)

::: omnist.document
    options:
      show_root_heading: false

---

## Schema Model (`omnist.schema`)

::: omnist.schema
    options:
      show_root_heading: false

---

## OSD Grammar & Serialization (`omnist.osd`)

::: omnist.osd
    options:
      show_root_heading: false

---

## Codecs & Formats (`omnist.formats` & `omnist.oml`)

::: omnist.formats
    options:
      show_root_heading: false

::: omnist.oml
    options:
      show_root_heading: false

---

## Inference & Materialization (`omnist.infer` & `omnist.deserialize`)

::: omnist.infer
    options:
      show_root_heading: false

::: omnist.deserialize
    options:
      show_root_heading: false

---

## Operations & Linting (`omnist.ops`)

::: omnist.ops
    options:
      show_root_heading: false

::: omnist.ops.lint
    options:
      show_root_heading: false

::: omnist.ops.minimize
    options:
      show_root_heading: false

::: omnist.ops.prune
    options:
      show_root_heading: false

::: omnist.ops.subschema
    options:
      show_root_heading: false

::: omnist.ops.extract
    options:
      show_root_heading: false

::: omnist.ops.isomorphic
    options:
      show_root_heading: false

::: omnist.ops.signature
    options:
      show_root_heading: false

---

## Adjustment Reports (`omnist.report`)

::: omnist.report
    options:
      show_root_heading: false

---

## Format Registry (`omnist.registry`)

::: omnist.registry
    options:
      show_root_heading: false

---

## Errors & Exceptions (`omnist.errors`)

::: omnist.errors
    options:
      show_root_heading: false

---

## CLI (`omnist.cli`)

::: omnist.cli
    options:
      show_root_heading: false
