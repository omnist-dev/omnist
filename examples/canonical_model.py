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
    "type":   string,
    "server": string,
    "port":   integer,
}
record Service {
    "host":            string,      # required (default cardinality [1,1])
    "port":            integer,
    "databases" [1,]:  Database,    # one or more (array of records)
    "tags" [0,]:       string,      # zero or more (array of scalars)
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
                 'tags: "prod"\n'
                 'tags: "us-east"\n'
                 'databases: { type: "prod"; server: "db1.internal.example.com"; port: 5432 }\n'
                 'databases: { type: "test"; server: "db2.internal.example.com"; port: 5433 }\n')
    print("valid:", s.validate(Doc(o)).ok)

    print("\n== and the identical Document from JSON/YAML/TOML, too ==")
    # Field order matches TOML's syntax constraint (simple keys before
    # array-of-tables), so the same edge order round-trips through all four.
    j = read_json('{"host":"api.internal","port":8443,"tags":["prod","us-east"],'
                  '"databases":[{"type":"prod","server":"db1.internal.example.com","port":5432},'
                  '{"type":"test","server":"db2.internal.example.com","port":5433}]}')
    y = read_yaml("host: api.internal\nport: 8443\n"
                  "tags:\n  - prod\n  - us-east\n"
                  "databases:\n"
                  "  - type: prod\n    server: db1.internal.example.com\n    port: 5432\n"
                  "  - type: test\n    server: db2.internal.example.com\n    port: 5433\n")
    t = read_toml('host = "api.internal"\nport = 8443\ntags = ["prod", "us-east"]\n'
                  '[[databases]]\ntype = "prod"\n'
                  'server = "db1.internal.example.com"\nport = 5432\n'
                  '[[databases]]\ntype = "test"\n'
                  'server = "db2.internal.example.com"\nport = 5433\n')
    print("oml == json == yaml == toml:", o == j == y == t)

    print("\n== XML keeps the document element as one top-level edge ==")
    x = read_xml("<service><host>api.internal</host><port>8443</port>"
                 "<tags>prod</tags><tags>us-east</tags>"
                 "<databases><type>prod</type><server>db1.internal.example.com</server><port>5432</port></databases>"
                 "<databases><type>test</type><server>db2.internal.example.com</server><port>5433</port></databases>"
                 "</service>")
    print("xml document:", x)

    print("\n== a rejected document, errors at exact paths ==")
    bad = doc({"host": "api.internal", "port": 8443,
               "databases": [{"type": "prod", "server": 7, "port": 5432}]})
    print(s.validate(bad))

    print("\n== compatible_with: adding an array field is backward-compatible ==")
    v1 = parse_schema('record Database { "type": string, "server": string, "port": integer }\n'
                      'record Service { "host": string, "port": integer, '
                      '"databases" [1,]: Database }\nroot Service')
    v2 = parse_schema('record Database { "type": string, "server": string, "port": integer }\n'
                      'record Service { "host": string, "port": integer, '
                      '"databases" [1,]: Database, "tags" [0,]: string }\n'
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
