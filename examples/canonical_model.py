#!/usr/bin/env python3
"""The canonical model end to end: edge-list Document,
record/Ref schema with exactly seven scalars, field cardinality, validation,
operations, and codecs.

This exercises ``omnist`` — the implementation of the design in
``docs/design/model.md``.

Run: python3 examples/canonical_model.py
"""
from omnist import (
    Doc,
    doc,
    parse_schema,
    read_json,
    read_oml,
    read_toml,
    read_xml,
    read_yaml,
    to_osd,
)

SCHEMA = """
record Database {
    "engine": string,
    "port": integer,
}
record Service {
    "host":           string,
    "port":           integer,
    "database":       Database,      # required (default cardinality [1,1])
    "replicas" [0,]:  Database,      # zero or more (array of records)
    "backup" [0,1]:   Database,      # optional
}
root Service
"""


def main():
    s = parse_schema(SCHEMA)

    print("== schema round-trips through to_osd ==")
    print("equivalent:", s.equivalent(parse_schema(to_osd(s))))

    print("\n== the Service, in OML (omnist's own format) ==")
    o = read_oml('host: "api.internal"\n'
                 'port: 8443\n'
                 'database: { engine: "postgres"; port: 5432 }\n'
                 'replicas: { engine: "postgres"; port: 5433 }\n')
    print("valid:", s.validate(Doc(o)).ok)

    print("\n== and the identical Document from JSON/YAML/TOML, too ==")
    j = read_json('{"host":"api.internal","port":8443,'
                  '"database":{"engine":"postgres","port":5432},'
                  '"replicas":[{"engine":"postgres","port":5433}]}')
    y = read_yaml("host: api.internal\nport: 8443\n"
                  "database:\n  engine: postgres\n  port: 5432\n"
                  "replicas:\n  - engine: postgres\n    port: 5433\n")
    t = read_toml('host = "api.internal"\nport = 8443\n'
                  '[database]\nengine = "postgres"\nport = 5432\n'
                  '[[replicas]]\nengine = "postgres"\nport = 5433\n')
    print("oml == json == yaml == toml:", o == j == y == t)

    print("\n== XML keeps the document element as one top-level edge ==")
    x = read_xml("<service><host>api.internal</host><port>8443</port>"
                 "<database><engine>postgres</engine><port>5432</port></database>"
                 "<replicas><engine>postgres</engine><port>5433</port></replicas>"
                 "</service>")
    print("xml document:", x)

    print("\n== a rejected document, errors at exact paths ==")
    bad = doc({"host": "api.internal", "port": 8443,
               "database": {"engine": 7, "port": 5432}})
    print(s.validate(bad))

    print("\n== compatible_with: adding an optional field is backward-compatible ==")
    v1 = parse_schema('record Database { "engine": string, "port": integer }\n'
                      'record Service { "host": string, "port": integer, '
                      '"database": Database }\nroot Service')
    v2 = parse_schema('record Database { "engine": string, "port": integer }\n'
                      'record Service { "host": string, "port": integer, '
                      '"database": Database, "backup" [0,1]: Database }\n'
                      'root Service')
    print("v1.compatible_with(v2):", v1.compatible_with(v2))
    print("v2.compatible_with(v1):", v2.compatible_with(v1))

    print("\n== normalize computes the canonical minimal schema via partition refinement ==")
    dup = parse_schema('record A { "x": integer }\nrecord B { "x": integer }\n'
                       'record R { "a": A, "b": B }\nroot R')
    n = dup.normalize()
    print("definitions before:", sorted(dup.env), "after:", sorted(n.env))
    print("equivalent:", dup.equivalent(n))


if __name__ == "__main__":
    main()
