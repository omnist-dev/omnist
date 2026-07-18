"""Execute the key snippets shown in the docs, so they can't silently rot."""
import pytest

import omnist as ds
from omnist import (
    Doc,
    DocumentError,
    Format,
    SchemaError,
    WriteError,
    WriteReport,
    doc,
    field,
    infer,
    nullable,
    parse_schema,
    read_json,
    read_oml,
    read_toml,
    read_xml,
    read_yaml,
    record,
    ref,
    register_format,
    schema,
    t,
    to_osd,
)


def test_readme_at_a_glance():
    s = parse_schema('record Database { "type": string, "server": string, "port": integer }\n'
                     'record Service { "host": string, "port": integer, '
                     '"databases" [1,]: Database, "tags" [0,]: string }\nroot Service')
    assert s.validate(doc({"host": "api.internal", "port": 8443,
                           "databases": [{"type": "prod",
                                          "server": "db1.internal.example.com",
                                          "port": 5432}],
                           "tags": ["prod", "us-east"]})).ok
    assert ds.__version__ == "0.7.2"


def test_quickstart():
    d = Doc.from_oml('name: "Ann"')
    s = parse_schema('record Person { "name": string }\nroot Person')
    assert s.validate(d).ok

    assert infer([doc({"name": "Ann"}), doc({"name": "Bo"})]).to_osd() == (
        'record Root {\n    "name": string,\n}\nroot Root\n')


def test_readme_60_second_tour_infer():
    assert infer([doc({"id": 1, "tags": ["a"]})]).to_osd() == (
        'record Root {\n    "id": integer,\n    "tags": string,\n}\nroot Root\n')


def test_guide_documents():
    d = doc({"name": "Ann", "tag": ["x", "y"]})
    assert d.labels() == ["name", "tag"]
    assert d.count("tag") == 2
    assert d.get_one("name").value == "Ann"
    assert [c.value for c in d.get("tag")] == ["x", "y"]
    assert d.to_data() == [("name", "Ann"), ("tag", "x"), ("tag", "y")]
    assert d.to_grouped() == {"name": "Ann", "tag": ["x", "y"]}


def test_guide_oml_native_format():
    import datetime
    d = Doc.from_oml('\nname: "Ann"\ntag: "x"\ntag: "y"\njoined: 2024-01-01\n')
    assert d.to_grouped() == {"name": "Ann", "tag": ["x", "y"],
                              "joined": datetime.date(2024, 1, 1)}
    assert d.to_oml() == 'name: "Ann"\ntag: "x"\ntag: "y"\njoined: 2024-01-01'


def test_guide_oml_comments_and_arrays():
    assert read_oml('a: 1  # this note is gone\n') == [('a', 1)]
    assert read_oml('b: [1, 2, 3]') == [('b', 1), ('b', 2), ('b', 3)]


def test_guide_osd_any_type():
    s = parse_schema('''
record Event {
    "id":      string,
    "type":    string,
    "data":    any,
}
root Event
''')
    assert s.validate(doc({"id": "evt_1", "type": "user.created",
                           "data": {"name": "Ann", "email": "a@x.com"}})).ok
    assert s.validate(doc({"id": "evt_2", "type": "payment.settled",
                           "data": {"amount_cents": 1250, "currency": "EUR"}})).ok


def test_guide_operations_lint():
    from omnist.ops.lint import lint
    s = parse_schema('''
record Customer { "name": string }
record Employee { "name": string }
root Customer
''')
    findings = lint(s)
    assert any(f.code == "duplicate-record" for f in findings)


def test_guide_reading_writing_compact_mode():
    from omnist import write_oml
    node = [("name", "Ada"), ("tags", [("tag", "x"), ("tag", "y")])]
    assert write_oml(node, indent=None) == 'name: "Ada"; tags: { tag: "x"; tag: "y" }'


def test_formats_oml_compact_write():
    from omnist import write_oml
    node = [("name", "Ada"), ("tags", [("tag", "x"), ("tag", "y")])]
    assert write_oml(node) == 'name: "Ada"\ntags: {\n  tag: "x"\n  tag: "y"\n}'
    assert write_oml(node, indent=None) == 'name: "Ada"; tags: { tag: "x"; tag: "y" }'


def test_formats_oml_edge_order_is_data_but_validation_ignores_it():
    doc1 = Doc.from_oml('a: 1\nb: 2')
    doc2 = Doc.from_oml('b: 2\na: 1')
    assert doc1 != doc2  # different Documents, order is data

    s = parse_schema('record R { "a": integer, "b": integer }\nroot R')
    assert s.validate(doc1).ok
    assert s.validate(doc2).ok  # same result; validation ignores order


def test_formats_oml_maps_to_the_same_document_as_the_builder():
    import datetime
    node = read_oml('''
name: "Ann"
role: "dev"
joined: 2024-01-01
tag: "x"
tag: "y"
manager: null
''')
    built = doc({
        "name": "Ann",
        "role": "dev",
        "joined": datetime.date(2024, 1, 1),
        "tag": ["x", "y"],
        "manager": None,
    })
    assert node == built.to_data()


def test_schema_page_osd_shape_and_builder_equivalence():
    OSD = '''
    record Address { "street": string, "city": string }

    record User {
        "name":          string,
        "nickname" [0,1]: string,
        "emails" [1,]:    string,
        "address":       Address,
        "note":          string?,
    }
    root User
    '''
    s = parse_schema(OSD)
    assert s.validate(doc({"name": "Ann", "emails": ["a@x.com"],
                           "address": {"street": "1 Main", "city": "London"},
                           "note": None})).ok

    address = record(field("street", t.string), field("city", t.string))
    user = record(
        field("name",     t.string),
        field("nickname", t.string, min=0, max=1),
        field("emails",   t.string, min=1, max=None),
        field("address",  ref("Address")),
        field("note",     nullable(t.string)),
    )
    s2 = schema(ref("User"), User=user, Address=address)
    assert s.equivalent(s2)


def test_schema_page_to_osd_pretty_and_compact():
    s = parse_schema('record Car { "license": string }\nroot Car')
    assert to_osd(s) == 'record Car {\n    "license": string,\n}\nroot Car\n'
    assert to_osd(s, indent=None) == 'record Car { "license": string } root Car\n'


def test_schema_page_empty_schemas():
    empty = parse_schema('record A { "x": B }\nrecord B { "y": A }\nroot A')
    other = parse_schema('record C { "z": integer }\nroot C')

    assert empty.is_empty()
    assert empty.compatible_with(other)
    assert not other.compatible_with(empty)

    empty2 = parse_schema('record P { "q": P }\nroot P')
    assert empty.equivalent(empty2)

    s = parse_schema('record R { "x" [0,1]: Dead }\nrecord Dead { "d": Dead }\n'
                     'root R')
    assert not s.is_empty()
    p = s.prune()
    assert p.to_osd() == 'record R {\n}\nroot R\n'
    assert s.equivalent(parse_schema(to_osd(s, indent=None)))


def test_schema_page_extract():
    quote_order = parse_schema('''
    record Root  { "quote" [0,1]: Quote, "order" [0,1]: Order }
    record Quote { "line" [1,]: Line }
    record Order { "line" [1,]: OrderLine }
    record Line  { "desc": string, "price": number }
    record OrderLine { "product" [1,]: Product, "qty": integer }
    record Product   { "desc": string, "price": number }
    root Root
    ''')

    ex = quote_order.extract("quote", "line", "desc", "price")
    assert sorted(ex.env) == ["Line", "Quote", "Root"]
    assert ex.compatible_with(quote_order)

    s = parse_schema('record R { "must": integer, "opt" [0,1]: string }\nroot R')
    with pytest.raises(SchemaError) as exc:
        s.extract("opt")
    assert str(exc.value) == (
        "no valid subschema: removing label 'must' deletes a mandatory "
        "field of record 'R'")


def test_schema_page_validation_errors():
    OSD = '''
    record Address { "street": string, "city": string }
    record User {
        "name":          string,
        "nickname" [0,1]: string,
        "emails" [1,]:    string,
        "address":       Address,
        "note":          string?,
    }
    root User
    '''
    s = parse_schema(OSD)
    bad = doc({"emails": [], "address": {"street": "x", "city": "y"}})
    msgs = {e.message for e in s.validate(bad).errors}
    assert any("'name' occurs 0 time(s), expected exactly 1" in m for m in msgs)
    assert any("'emails' occurs 0 time(s), expected at least 1" in m for m in msgs)
    assert any("'note' occurs 0 time(s), expected exactly 1" in m for m in msgs)


def test_schema_page_operations_and_infer():
    v1 = parse_schema('record R { "host": string }\nroot R')
    v2 = parse_schema('record R { "host": string, "port" [0,1]: integer }\nroot R')
    assert v1.compatible_with(v2)
    assert not v2.compatible_with(v1)

    # equivalent: same structure, different record name
    s1 = parse_schema('record R { "x": integer }\nroot R')
    s2 = parse_schema('record Alias { "x": integer }\nroot Alias')
    assert s1.equivalent(s2)
    assert s1.compatible_with(s2)
    assert s2.compatible_with(s1)

    # normalize: structurally-identical records merged
    s = parse_schema('record A { "x": integer }\nrecord B { "x": integer }\nroot A')
    n = s.normalize()
    assert n.equivalent(s)
    assert list(n.env.keys()) == ["A"]  # B merged into A

    assert infer([doc({"host": "b", "port": 80}), doc({"host": "a"})]).to_osd() == (
        'record Root {\n    "host": string,\n    "port" [0,1]: integer,\n}\nroot Root\n')

    # infer does NOT auto-normalize: duplicates stay until .normalize()
    s = infer([doc({"home": {"city": "London"}, "work": {"city": "Leeds"}})])
    assert sorted(s.env) == ["Home", "Root", "Work"]
    assert sorted(s.normalize().env) == ["Home", "Root"]


def test_guide_editing():
    d = doc({"name": "Ann"})
    d.add("tag", "x").add("tag", "y")
    d.set("name", "Bob")       # replace all 'name' edges with one ('set' = 'remove' + 'add')
    d.remove("tag")
    assert d.to_grouped() == {"name": "Bob"}


def test_guide_editing_set_replace_all_on_a_repeated_label():
    # guide.md's "Documents" section, set() paragraph: set() removes every
    # edge under the label, then inserts one new edge at the position of the
    # first old occurrence (or appends, if the label was absent).
    d = doc({"tag": "x"})
    d.add("tag", "y").add("other", 1)
    d.set("tag", "z")
    assert d.to_data() == [("tag", "z"), ("other", 1)]
    assert d.count("tag") == 1


def test_guide_builder_matches_osd():
    address = record(field("street", t.string), field("city", t.string))
    user = record(field("name", t.string),
                  field("emails", t.string, min=1, max=None),
                  field("address", ref("Address")),
                  field("status", t.string))
    s = schema(ref("User"), User=user, Address=address)
    osd = parse_schema('record Address { "street": string, "city": string }\n'
                       'record User { "name": string, "emails" [1,]: string, '
                       '"address": Address, "status": string }\nroot User')
    assert s.equivalent(osd)


def test_guide_validation_error():
    r = parse_schema('record R { "items" [1,]: integer }\nroot R').validate(
            doc({"items": []}))
    assert not r.ok
    assert r.errors[0].path == "$" and "at least 1" in r.errors[0].message


def test_guide_operations_are_methods():
    v1 = parse_schema('record R { "host": string }\nroot R')
    v2 = parse_schema('record R { "host": string, "port" [0,1]: integer }\nroot R')
    assert v1.compatible_with(v2)
    assert not v2.compatible_with(v1)
    assert not v1.equivalent(v2)
    n = v1.normalize()
    assert n.equivalent(v1)


def test_guide_empty_schemas():
    v1 = parse_schema('record R { "host": string }\nroot R')
    empty = parse_schema('record A { "x": B }\nrecord B { "y": A }\nroot A')
    assert empty.is_empty()
    assert empty.compatible_with(v1)


def test_readme_schema_directed_deserialization():
    import datetime
    s2 = parse_schema('record R { "d": date }\nroot R')
    assert read_json('{"d": "2024-01-01"}', schema=s2) == \
        [("d", datetime.date(2024, 1, 1))]


def test_guide_infer():
    s = infer([doc({"id": 1, "tags": ["a"]}), doc({"id": 2, "tags": ["b", "c"]})])
    assert s.to_osd() == ('record Root {\n    "id": integer,\n'
                          '    "tags" [0,]: string,\n}\nroot Root\n')


def test_api_docs_infer_with_report_allow_any():
    # Mirrors the docs/api.md and docs/cli.md --allow-any examples.
    from omnist import AnyType, infer_with_report
    samples = [doc({"data": {"x": 1}, "score": 1}),
               doc({"data": 5, "score": "hi"})]
    schema_out, fallbacks = infer_with_report(samples, allow_any=True)
    lines = [f"{fb.location} — {fb.reason}" for fb in fallbacks]
    assert lines == [
        "Root.data — mixes objects and values",
        "Root.score — values of more than one scalar kind (integer, string)",
    ]
    by_label = {f.label: f.type for f in schema_out.env["Root"].fields}
    assert isinstance(by_label["data"], AnyType)
    assert isinstance(by_label["score"], AnyType)
    # default (no opt-in) still raises
    with pytest.raises(SchemaError):
        infer(samples)


def test_guide_real_life_example():
    ORDER = '''
    record Address  { "street": string, "city": string }
    record LineItem { "sku": string, "qty": integer, "price": number }
    record Order {
        "id":       string,
        "status":   string,
        "total":    number,
        "address":  Address,
        "items" [1,]: LineItem,
        "coupon" [0,1]: string,
    }
    root Order
    '''
    s = parse_schema(ORDER)

    good = Doc.from_oml('''
id: "A1"
status: "shipped"
total: 29.97
address: { street: "1 Main St"; city: "London" }
items: { sku: "W"; qty: 3; price: 9.99 }
''')
    assert s.validate(good).ok

    bad = Doc.from_oml('''
id: "A2"
status: "shipped"
total: "ten"
address: { street: "x"; city: "y" }
''')
    msgs = {e.message for e in s.validate(bad).errors}
    assert any("expected number, got string" in m for m in msgs)
    assert any("at least 1" in m for m in msgs)


def test_example_all_formats_one_document():
    s = parse_schema('''
        record Address  { "street": string, "city": string }
        record LineItem { "sku": string, "qty": integer, "price": number }
        record Order {
            "id": string,
            "status": string,
            "total": number,
            "address": Address,
            "items" [1,]: LineItem,
            "coupon" [0,1]: string,
        }
        record Root { "order": Order }
        root Root
    ''')
    j = read_json('{"order":{"id":"A1","status":"shipped","total":29.97,'
                  '"address":{"street":"1 Main","city":"London"},'
                  '"items":[{"sku":"W","qty":3,"price":9.99},'
                  '{"sku":"G","qty":1,"price":9.99}]}}')
    y = read_yaml("order:\n  id: A1\n  status: shipped\n  total: 29.97\n"
                  "  address: {street: 1 Main, city: London}\n"
                  "  items:\n    - {sku: W, qty: 3, price: 9.99}\n"
                  "    - {sku: G, qty: 1, price: 9.99}\n")
    tm = read_toml('[order]\nid="A1"\nstatus="shipped"\ntotal=29.97\n'
                   '[order.address]\nstreet="1 Main"\ncity="London"\n'
                   '[[order.items]]\nsku="W"\nqty=3\nprice=9.99\n'
                   '[[order.items]]\nsku="G"\nqty=1\nprice=9.99\n')
    x = read_xml("<order><id>A1</id><status>shipped</status><total>29.97</total>"
                 "<address><street>1 Main</street><city>London</city></address>"
                 "<items><sku>W</sku><qty>3</qty><price>9.99</price></items>"
                 "<items><sku>G</sku><qty>1</qty><price>9.99</price></items></order>")
    assert j == y == tm == x
    assert all(s.validate(Doc(d)).ok for d in (j, y, tm, x))


def test_example_doc_all_formats_one_document_incl_oml():
    s = parse_schema('''
        record Address  { "street": string, "city": string }
        record LineItem { "sku": string, "qty": integer, "price": number }
        record Order {
            "id": string,
            "status": string,
            "total": number,
            "address": Address,
            "items" [1,]: LineItem,
            "coupon" [0,1]: string,
        }
        record Root { "order": Order }
        root Root
    ''')
    j = read_json('{"order":{"id":"A1","status":"shipped","total":29.97,'
                  '"address":{"street":"1 Main","city":"London"},'
                  '"items":[{"sku":"W","qty":3,"price":9.99},'
                  '{"sku":"G","qty":1,"price":9.99}]}}')
    o = read_oml('''
order: {
    id: "A1"
    status: "shipped"
    total: 29.97
    address: { street: "1 Main"; city: "London" }
    items: { sku: "W"; qty: 3; price: 9.99 }
    items: { sku: "G"; qty: 1; price: 9.99 }
}
''')
    assert j == o
    assert s.validate(Doc(o)).ok
    assert Doc(o).to_json() == (
        '{"order": {"id": "A1", "status": "shipped", "total": 29.97, '
        '"address": {"street": "1 Main", "city": "London"}, '
        '"items": [{"sku": "W", "qty": 3, "price": 9.99}, '
        '{"sku": "G", "qty": 1, "price": 9.99}]}}')

    bad = Doc.from_oml('''
order: {
    id: "A2"
    status: "shipped"
    total: "ten"
    address: { street: "x"; city: "y" }
}
''')
    msgs = {e.message for e in s.validate(bad).errors}
    assert any("expected number, got string" in m for m in msgs)
    assert any("at least 1" in m for m in msgs)


def test_example_rejected_order():
    s = parse_schema('record LineItem { "sku": string }\n'
                     'record Order { "status": integer, '
                     '"items" [1,]: LineItem }\n'
                     'record Root { "order": Order }\nroot Root')
    bad = Doc.from_json('{"order":{"status":"lost","items":[]}}')
    msgs = {e.message for e in s.validate(bad).errors}
    assert any("expected integer" in m for m in msgs)
    assert any("at least 1" in m for m in msgs)


def test_formats_docs_snippets():
    from omnist import write_json
    assert write_json([("tag", "x"), ("tag", "y")]) == '{"tag": ["x", "y"]}'
    assert write_json([("tag", "x")]) == '{"tag": "x"}'
    assert read_xml("<t><m>a</m><x>1</x><m>b</m></t>") == \
        [("t", [("m", "a"), ("x", 1), ("m", "b")])]      # interleaving preserved


def test_formats_json_docs_raw_array_edge_list():
    assert read_json('{"tags": ["x", "y"]}') == [("tags", "x"), ("tags", "y")]


def test_formats_yaml_docs_raw_sequence_edge_list():
    assert read_yaml('tags: [x, y]') == [("tags", "x"), ("tags", "y")]


def test_formats_toml_docs_raw_array_of_tables_edge_list():
    assert read_toml("""
[[items]]
sku = "W"
[[items]]
sku = "G"
""") == [("items", [("sku", "W")]), ("items", [("sku", "G")])]


def test_formats_xml_docs_opener():
    d = Doc(read_xml("<person><name>Ann</name><tags>x</tags><tags>y</tags></person>"))
    assert d.to_json() == '{"person": {"name": "Ann", "tags": ["x", "y"]}}'


def test_formats_xml_docs_raw_repeated_element_edge_list():
    assert read_xml('<items><item>x</item><item>y</item></items>') == \
        [("items", [("item", "x"), ("item", "y")])]


def test_api_docs_schema_directed_deserialization():
    import datetime
    s = parse_schema('record R { "d": date, "n": number }\nroot R')
    node = read_json('{"d": "2024-01-01", "n": 3}', schema=s)
    assert node == [("d", datetime.date(2024, 1, 1)), ("n", 3.0)]


def test_api_docs_adjustment_reports():
    d = doc({"a": 1, "b": None})
    assert d.to_toml() == "a = 1\n"
    rep = WriteReport()
    d.to_toml(report=rep)
    assert [(a.code, a.severity) for a in rep] == [("null.omitted", "warning")]
    assert [(a.code, a.severity) for a in d.check_toml()] == \
        [(a.code, a.severity) for a in rep]
    with pytest.raises(WriteError):
        d.to_toml(strict=True)


def test_api_docs_format_registry():
    register_format(Format(
        name="lines",
        read=lambda text: [("n", int(x)) for x in text.split()],
        write=lambda node, **opts: " ".join(str(v) for _, v in node),
    ))
    assert Doc.from_format("lines", "1 2 3").to_format("lines") == "1 2 3"


def test_api_docs_version():
    assert ds.__version__ == "0.7.2"


def test_api_docs_schema_raises():
    from omnist import SchemaError
    from omnist.schema import Ref, Scalar, Schema

    # root isn't a Ref
    try:
        Schema(Scalar("string"))
        assert False, "expected SchemaError"
    except SchemaError:
        pass

    # an env entry isn't a Record
    try:
        Schema(Ref("R"), {"R": Scalar("string")})
        assert False, "expected SchemaError"
    except SchemaError:
        pass

    # a Ref names an entry not present in env
    try:
        Schema(Ref("R"), {})
        assert False, "expected SchemaError"
    except SchemaError:
        pass


def test_api_docs_string_ambiguous_adjustment():
    d = doc({"x": "42"})
    rep = WriteReport()
    d.to_xml(report=rep)
    assert [(a.code, a.severity) for a in rep] == [("string.ambiguous", "warning")]


def test_schema_docs_linting_example():
    from omnist import lint

    s = parse_schema('record Employee { "name": string }\n'
                     'record Customer { "name": string }\n'
                     'record Company  { "employee": Employee, "customer": Customer }\n'
                     'root Company')
    assert [(f.code, f.location) for f in lint(s)] == [
        ("duplicate-record", "Customer, Employee")]


def test_deserialization_docs_core_distinction():
    import datetime

    text = '{"d": "2024-01-01", "n": 3}'

    no_schema = read_json(text)
    assert no_schema == [("d", "2024-01-01"), ("n", 3)]
    assert type(dict(no_schema)["d"]) is str

    s = parse_schema('record R { "d": date, "n": number }\nroot R')
    with_schema = read_json(text, schema=s)
    assert with_schema == [("d", datetime.date(2024, 1, 1)), ("n", 3.0)]
    assert type(dict(with_schema)["d"]) is datetime.date


def test_deserialization_docs_per_format_no_schema_baseline():
    import datetime

    s = parse_schema('record D { "d": date }\nroot D')

    assert type(dict(read_json('{"d": "2024-01-01"}'))["d"]) is str
    assert type(dict(read_json('{"d": "2024-01-01"}', schema=s))["d"]) is datetime.date

    assert type(dict(read_yaml('d: 2024-01-01'))["d"]) is datetime.date
    assert type(dict(read_yaml('d: 2024-01-01', schema=s))["d"]) is datetime.date

    assert type(dict(read_toml('d = 2024-01-01'))["d"]) is datetime.date
    assert type(dict(read_toml('d = 2024-01-01', schema=s))["d"]) is datetime.date

    assert type(dict(read_xml('<d>2024-01-01</d>'))["d"]) is str
    assert type(dict(read_xml('<d>2024-01-01</d>', schema=s))["d"]) is datetime.date


def test_deserialization_docs_parse_error_not_value_exact():
    from omnist import ParseError

    s = parse_schema('record R { "n": integer }\nroot R')
    with pytest.raises(ParseError):
        read_json('{"n": "abc"}', schema=s)


def test_deserialization_docs_parse_error_structured_errors():
    from omnist import ParseError

    s2 = parse_schema('record R { "a": integer }\nroot R')
    with pytest.raises(ParseError) as exc:
        read_json('{"a": 1, "b": "extra"}', schema=s2)
    err = exc.value.errors[0]
    assert (err.path, err.code, err.message) == ("$.b", "unexpected-field", "unexpected field")


def test_deserialization_docs_materialize():
    import datetime

    from omnist import materialize

    s = parse_schema('record R { "d": date }\nroot R')
    node = read_json('{"d": "2024-01-01"}')
    assert node == [("d", "2024-01-01")]
    assert materialize(node, s) == [("d", datetime.date(2024, 1, 1))]


def test_model_docs_count1_no_schema_param():
    import inspect

    from omnist import write_json, write_toml, write_xml, write_yaml
    for fn in (write_json, write_yaml, write_toml, write_xml):
        assert "schema" not in inspect.signature(fn).parameters
    assert write_json([("tag", "x")]) == '{"tag": "x"}'
    assert write_json([("tag", "x"), ("tag", "y")]) == '{"tag": ["x", "y"]}'


def test_model_docs_appendix_worked_example():
    s = parse_schema('''
record Database {
    "type":   string,
    "server": string,
    "port":   integer,
}
record Service {
    "host":            string,
    "port":            integer,
    "databases" [1,]:  Database,
    "tags" [0,]:       string,
}
root Service
''')
    node = [("host", "api.internal"),
            ("port", 8443),
            ("databases", [("type", "prod"),
                           ("server", "db1.internal.example.com"), ("port", 5432)]),
            ("databases", [("type", "test"),
                           ("server", "db2.internal.example.com"), ("port", 5433)]),
            ("tags", "prod"),
            ("tags", "us-east")]
    d = Doc(node)
    assert s.validate(d).ok
    assert d.to_json() == (
        '{"host": "api.internal", "port": 8443, "databases": '
        '[{"type": "prod", "server": "db1.internal.example.com", "port": 5432}, '
        '{"type": "test", "server": "db2.internal.example.com", "port": 5433}], '
        '"tags": ["prod", "us-east"]}')



def test_formats_json_reading_no_schema():
    assert read_json('{"d": "2024-01-01", "n": 3}') == [("d", "2024-01-01"), ("n", 3)]
    assert isinstance(dict(read_json('{"d": "2024-01-01", "n": 3}'))["d"], str)


def test_formats_json_reading_with_schema():
    import datetime
    s = parse_schema('record R { "d": date, "n": number }\nroot R')
    assert read_json('{"d": "2024-01-01", "n": 3}', schema=s) == \
        [("d", datetime.date(2024, 1, 1)), ("n", 3.0)]
    assert Doc.from_json('{"d": "2024-01-01", "n": 3}', schema=s).to_data() == \
        [("d", datetime.date(2024, 1, 1)), ("n", 3.0)]


def test_formats_json_writing():
    assert Doc.of({"tag": ["x", "y"]}).to_json() == '{"tag": ["x", "y"]}'


def test_formats_json_docs_special_float_substitution():
    from omnist import write_json
    assert write_json([("a", float("inf"))]) == '{"a": null}'


def test_formats_yaml_reading_no_schema():
    import datetime
    node = read_yaml("d: 2024-01-01")
    assert node == [("d", datetime.date(2024, 1, 1))]
    assert isinstance(dict(node)["d"], datetime.date)
    node2 = read_yaml("dt: 2024-01-01T12:00:00")
    assert node2 == [("dt", datetime.datetime(2024, 1, 1, 12, 0))]


def test_formats_yaml_reading_with_schema():
    import datetime
    s = parse_schema('record R { "d": date, "n": number }\nroot R')
    assert read_yaml("d: 2024-01-01\nn: 3", schema=s) == \
        [("d", datetime.date(2024, 1, 1)), ("n", 3.0)]
    assert Doc.from_yaml("d: 2024-01-01\nn: 3", schema=s).to_data() == \
        [("d", datetime.date(2024, 1, 1)), ("n", 3.0)]


def test_formats_yaml_writing():
    import datetime

    from omnist import write_yaml
    assert write_yaml([("name", "Ada"), ("born", datetime.date(1815, 12, 10))]) == \
        "name: Ada\nborn: 1815-12-10\n"
    assert Doc.of({"name": "Ada"}).to_yaml() == "name: Ada\n"


def test_formats_toml_reading_no_schema():
    import datetime
    node = read_toml("d = 2024-01-01")
    assert node == [("d", datetime.date(2024, 1, 1))]
    assert isinstance(dict(node)["d"], datetime.date)
    assert read_toml("t = 12:00:00") == [("t", datetime.time(12, 0))]
    assert read_toml("dt = 2024-01-01T12:00:00") == \
        [("dt", datetime.datetime(2024, 1, 1, 12, 0))]


def test_formats_toml_reading_with_schema():
    import datetime
    s = parse_schema('record R { "d": date, "n": number }\nroot R')
    assert read_toml("d = 2024-01-01\nn = 3", schema=s) == \
        [("d", datetime.date(2024, 1, 1)), ("n", 3.0)]
    assert Doc.from_toml("d = 2024-01-01\nn = 3", schema=s).to_data() == \
        [("d", datetime.date(2024, 1, 1)), ("n", 3.0)]


def test_formats_toml_writing():
    from omnist import write_toml
    assert write_toml([("id", "A1")]) == 'id = "A1"\n'
    assert Doc.of({"id": "A1"}).to_toml() == 'id = "A1"\n'


def test_formats_xml_reading_no_schema():
    node = read_xml("<r><n>30</n><f>3.5</f><ok>true</ok><d>2024-01-01</d></r>")
    assert node == [("r", [("n", 30), ("f", 3.5), ("ok", True), ("d", "2024-01-01")])]


def test_formats_xml_reading_with_schema():
    import datetime
    s = parse_schema('record Inner { "d": date, "n": number }\n'
                      'record R { "r": Inner }\nroot R')
    node = read_xml("<r><d>2024-01-01</d><n>3</n></r>", schema=s)
    assert node == [("r", [("d", datetime.date(2024, 1, 1)), ("n", 3.0)])]
    assert Doc.from_xml("<r><d>2024-01-01</d><n>3</n></r>", schema=s).to_data() == node


def test_formats_xml_writing():
    from omnist import write_xml
    assert write_xml([("order", [("id", "A1")])]) == "<order>\n  <id>A1</id>\n</order>\n"
    assert Doc.of({"order": {"id": "A1"}}).to_xml() == "<order>\n  <id>A1</id>\n</order>\n"


def test_formats_xml_docs_mixed_content_rejected():
    from omnist import ParseError
    try:
        read_xml("<p>Hello <b>world</b></p>")
        assert False, "expected ParseError"
    except ParseError as e:
        assert "mixed content" in str(e)

    try:
        read_xml("<p><b>world</b> tail</p>")
        assert False, "expected ParseError"
    except ParseError as e:
        assert "mixed content" in str(e)

    assert read_xml("<p>\n  <b>world</b>\n</p>") == [("p", [("b", "world")])]


def test_formats_oml_reading_no_schema():
    import datetime
    node = read_oml("d: 2024-01-01\nn: 3")
    assert node == [("d", datetime.date(2024, 1, 1)), ("n", 3)]
    assert isinstance(dict(node)["d"], datetime.date)
    node2 = read_oml('s: "2024-01-01"')
    assert node2 == [("s", "2024-01-01")]
    assert isinstance(dict(node2)["s"], str)


def test_formats_oml_reading_with_schema():
    import datetime
    s = parse_schema('record R { "d": date, "n": number }\nroot R')
    node = read_oml('d: "2024-01-01"\nn: 3', schema=s)
    assert node == [("d", datetime.date(2024, 1, 1)), ("n", 3.0)]
    assert Doc.from_oml('d: "2024-01-01"\nn: 3', schema=s).to_data() == node


def test_formats_oml_writing():
    from omnist import write_oml
    assert write_oml([("name", "Ada")]) == 'name: "Ada"'
    assert Doc.of({"name": "Ada"}).to_oml() == 'name: "Ada"'


def test_schema_any_type_envelope_example():
    s = parse_schema('''
record Event {
    "id":      string,
    "type":    string,
    "data":    any,
}
root Event
''')
    assert s.validate(doc({"id": "evt_1", "type": "user.created",
                           "data": {"name": "Ann", "email": "a@x.com"}})).ok
    assert s.validate(doc({"id": "evt_2", "type": "payment.settled",
                           "data": {"amount_cents": 1250, "currency": "EUR"}})).ok


def test_deserialization_any_type_pass_through_example():
    import datetime
    s = parse_schema('record R { "when": datetime, "data": any }' + chr(10) + 'root R')
    node = read_json('{"when": "2026-07-01T09:30:00", '
                     '"data": {"since": "2024-01-01"}}', schema=s)
    values = dict(node)
    assert isinstance(values["when"], datetime.datetime)
    assert dict(values["data"])["since"] == "2024-01-01"
    assert isinstance(dict(values["data"])["since"], str)


def test_why_omnist_compatible_with_worked_example():
    v1 = parse_schema('record R { "host": string }' + chr(10) + 'root R')
    v2 = parse_schema('record R { "host": string, "port" [0,1]: integer }' + chr(10) + 'root R')
    assert v1.compatible_with(v2)
    assert not v2.compatible_with(v1)


def test_why_omnist_jsonschema_has_no_compatibility_api():
    import jsonschema

    assert not hasattr(jsonschema, "compatible_with")
    assert not hasattr(jsonschema, "is_subset")

    v1 = {
        "type": "object",
        "properties": {"host": {"type": "string"}},
        "required": ["host"],
        "additionalProperties": False,
    }
    v2 = {
        "type": "object",
        "properties": {"host": {"type": "string"}, "port": {"type": "integer"}},
        "required": ["host"],
        "additionalProperties": False,
    }
    # jsonschema.validate only ever checks one document against one schema --
    # it proves nothing about whether v1's whole document set fits under v2.
    jsonschema.validate({"host": "x"}, v1)
    jsonschema.validate({"host": "x"}, v2)


def test_why_omnist_xml_drops_attributes_silently():
    from omnist import check_xml, read_xml

    assert read_xml('<a x="1"><b>hi</b></a>') == [("a", [("b", "hi")])]
    assert list(check_xml('<a x="1"><b>hi</b></a>')) == []


def test_why_omnist_xml_strips_namespaces_silently():
    from omnist import read_xml

    assert read_xml('<a xmlns:foo="http://x"><foo:b>hi</foo:b></a>') == \
        [("a", [("b", "hi")])]


def test_schema_docs_comments_no_roundtrip():
    s = parse_schema('''
# a top-level comment
record User {
    "name": string,  # inline, trailing a field
}
root User
''')
    assert [f.label for f in s.env["User"].fields] == ["name"]

    s2 = parse_schema('record R { "a": string } # this note is gone\nroot R')
    assert to_osd(s2) == 'record R {\n    "a": string,\n}\nroot R\n'


def test_formats_oml_comments_no_roundtrip():
    from omnist import write_oml

    node = read_oml("# a top comment\na: 1  # trailing comment\nb: 2\n")
    assert node == [("a", 1), ("b", 2)]

    assert read_oml('a: "x # y"') == [("a", "x # y")]
    assert read_oml("a: 'x # y'") == [("a", "x # y")]

    assert write_oml(read_oml("a: 1  # this note is gone\n")) == 'a: 1'


def test_formats_oml_arrays():
    from omnist import ParseError, write_oml

    src = ('a: "x"\n'
           'b: [1, 2, 3]\n'
           'c: true\n'
           'b: [4, 5, 6]\n')
    assert read_oml(src) == [
        ("a", "x"),
        ("b", 1), ("b", 2), ("b", 3),
        ("c", True),
        ("b", 4), ("b", 5), ("b", 6),
    ]

    assert read_oml('members: [{name: "Ann"}, {name: "Bob"}]') == [
        ("members", [("name", "Ann")]), ("members", [("name", "Bob")])]

    with pytest.raises(ParseError):
        read_oml("b: [[1,2]]")
    with pytest.raises(ParseError):
        read_oml("b: []")
    with pytest.raises(ParseError):
        read_oml("b: [1\n2]")

    assert read_oml("b: [\n  1, # one\n  2, # two\n]") == [("b", 1), ("b", 2)]
    assert read_oml("b: [1, 2, 3,]") == [("b", 1), ("b", 2), ("b", 3)]

    node = [("a", "x"), ("b", 1), ("b", 2), ("b", 3), ("c", True)]
    assert write_oml(node) == 'a: "x"\nb: 1\nb: 2\nb: 3\nc: true'
    assert write_oml(node, arrays=True) == 'a: "x"\nb: [1, 2, 3]\nc: true'
    assert read_oml(write_oml(node, arrays=True)) == node


def test_limitations_any_vacuity():
    s = parse_schema('''
record Event {
    "id":   string,
    "data": any,
}
root Event
''')

    # Two independently-parsed but identical schemas compare equivalent --
    # there's nothing inside `data`'s `any` region left to distinguish.
    s2 = parse_schema('''
record Event {
    "id":   string,
    "data": any,
}
root Event
''')
    assert s.equivalent(s2)


def test_limitations_depth_limit():
    deep = {"a": 1}
    for _ in range(205):
        deep = {"a": deep}

    try:
        infer([doc(deep)])
        raised = False
    except DocumentError as e:
        raised = "nesting exceeds the maximum depth" in str(e)

    assert raised
