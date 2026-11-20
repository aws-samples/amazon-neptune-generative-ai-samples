# MIT No Attribution
#
# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# SPDX-License-Identifier: MIT-0

"""
Go deeper, Cell G.4: the UFLPA rule as a W3C SHACL shape.

supply_chain_rdf() pulls one order's supply chain out of Neptune (openCypher, any depth)
and writes it as RDF with RDFLib; shacl_validate() runs pyshacl against a shape file. The
shape walks the chain with a SPARQL property path (nc:sourcesFrom+), the same any-depth
walk as the report's UFLPA rule, and the cell compares their verdicts.

Property graph to RDF: a node becomes a resource with an IRI, an edge becomes a triple,
and the order, which is only parameters in openCypher, becomes an nc:PurchaseOrder resource,
because SHACL validates focus nodes in the data.
"""
import re
from urllib.parse import quote, unquote

NC = "https://anycompany.example/procurement#"

SUPPLY_CHAIN = """
MATCH (s:Supplier {name: $supplier_name}), (r:Region {name: $region_name})
OPTIONAL MATCH (s)-[:SOURCES_FROM]->(t1:Company)
WITH s, r, collect(DISTINCT [s.name, t1.name]) AS first
OPTIONAL MATCH (s)-[:SOURCES_FROM*1..]->(a:Company)-[:SOURCES_FROM]->(b:Company)
WITH s, r, first, collect(DISTINCT [a.name, b.name]) AS deeper
OPTIONAL MATCH (s)-[:SOURCES_FROM*1..]->(c:Company)-[:ON_LIST]->(l:RestrictedList)
RETURN s.name AS supplier, r.name AS region, r.country AS country,
       [e IN first + deeper WHERE e[1] IS NOT NULL] AS sources, collect(DISTINCT [c.name, l.name]) AS listed
"""


def supply_chain_rdf(supplier_name, region_name):
    """One order's supply chain as RDF: the order (nc:PurchaseOrder) with its supplier and
    region (and the region's country), every nc:sourcesFrom edge at any tier, and which
    companies are nc:onList a restricted list."""
    from rdflib import Graph, Literal, Namespace, RDF, URIRef
    from verify import run_open_cypher
    row = run_open_cypher(SUPPLY_CHAIN, supplier_name=supplier_name, region_name=region_name)[0]
    nc = Namespace(NC)
    g = Graph()
    g.bind("nc", nc)
    company = lambda name: URIRef(_iri("company", name))
    order, s, r = (URIRef(_iri("order", f"{supplier_name} {region_name}")),
                   company(row["supplier"]), URIRef(_iri("region", row["region"])))
    g.add((order, RDF.type, nc.PurchaseOrder))
    g.add((order, nc.supplier, s))
    g.add((order, nc.region, r))
    g.add((r, nc.name, Literal(row["region"])))
    g.add((r, nc.country, Literal(row["country"] or "")))
    g.add((s, nc.name, Literal(row["supplier"])))
    for a, b in row["sources"]:
        g.add((company(a), nc.sourcesFrom, company(b)))
        g.add((company(b), nc.name, Literal(b)))
    for c, lst in row["listed"]:
        if c and lst:
            l = URIRef(_iri("list", lst))
            g.add((company(c), nc.onList, l))
            g.add((l, nc.name, Literal(lst)))
    return g


def ensure_pyshacl():
    """Install pyshacl into this kernel if it's missing, keeping RDFLib at the version
    graph-notebook (the %%oc magic) pins."""
    import importlib
    import importlib.util
    import subprocess
    import sys
    from importlib import metadata
    if importlib.util.find_spec("pyshacl") is not None:
        return
    try:
        pin = next(r.split(";")[0].replace(" ", "") for r in metadata.requires("graph-notebook") or []
                   if r.replace(" ", "").startswith("rdflib=="))
    except (metadata.PackageNotFoundError, StopIteration):
        pin = None
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet",
                           "pyshacl>=0.26,<0.29", *([pin] if pin else [])])
    importlib.invalidate_caches()


def _iri(kind, name):
    # No backslash inside the f-string: the notebook's Python may predate 3.12.
    slug = quote(re.sub(r"\s+", "_", name))
    return f"{NC}{kind}/{slug}"


def shacl_validate(data_graph, shapes_paths=("queries/uflpa_shape.ttl",)):
    """Validate with pyshacl against one or more Turtle shape files (read into one
    shapes graph, so a later file can use the sh:declare prefixes of the first).
    Returns (conforms, results), one result dict per sh:ValidationResult:
    {shape, focus, severity, message, value}."""
    from pyshacl import validate
    from rdflib import Graph, Namespace, RDF
    sh = Namespace("http://www.w3.org/ns/shacl#")
    shapes = Graph()
    for path in [shapes_paths] if isinstance(shapes_paths, str) else shapes_paths:
        shapes.parse(path, format="turtle")
    conforms, report, _ = validate(data_graph, shacl_graph=shapes, inference="none")

    def short(node):
        text = str(node) if node is not None else ""
        return text.rsplit("#", 1)[-1].rsplit("/", 1)[-1] if text.startswith("http") else text

    results = []
    for res in report.subjects(RDF.type, sh.ValidationResult):
        shape = report.value(res, sh.sourceShape)
        # A property shape is anonymous; name it after the node shape that holds it.
        parent = next(iter(shapes.subjects(sh.property, shape)), None) if shape is not None else None
        constraint = report.value(res, sh.sourceConstraint)
        named = next(iter(shapes.subjects(sh.sparql, constraint)), None) if constraint is not None else None
        results.append({
            "shape": short(named or parent or shape),
            # Keep the kind: the status shape targets the supplier, the others the order.
            "focus": unquote(str(report.value(res, sh.focusNode)).rsplit("#", 1)[-1]).replace("_", " "),
            "severity": short(report.value(res, sh.resultSeverity)),
            "message": str(report.value(res, sh.resultMessage) or ""),
            "value": short(report.value(res, sh.value)),
        })
    return conforms, sorted(results, key=lambda x: (x["shape"], x["value"]))
