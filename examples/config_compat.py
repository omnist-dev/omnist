#!/usr/bin/env python3
"""Is a config schema change safe to ship? `compatible_with` answers "is
every old document still valid under the new schema?" -- the flagship
backward-compatibility check no other schema tool provides.

Run: python3 examples/config_compat.py
"""
from omnist import parse_schema


def main():
    v1 = parse_schema(
        'record Cfg { "host": string, "port": integer, "tls" [0,1]: boolean }\n'
        'root Cfg'
    )

    # proposed v2a: add an optional field
    v2a = parse_schema(
        'record Cfg { "host": string, "port": integer, "tls" [0,1]: boolean, '
        '"timeout" [0,1]: integer }\n'
        'root Cfg'
    )

    # proposed v2b: make tls required
    v2b = parse_schema(
        'record Cfg { "host": string, "port": integer, "tls": boolean }\n'
        'root Cfg'
    )

    a = v1.compatible_with(v2a)
    print("v1.compatible_with(v2a):", a,
          "-- every old config is still valid; safe to ship")
    assert a is True

    b = v1.compatible_with(v2b)
    print("v1.compatible_with(v2b):", b,
          "-- old configs without \"tls\" now break")
    assert b is False


if __name__ == "__main__":
    main()
