"""Semantic Layer Workshop — helper library."""

import os, json, urllib.request, urllib.parse, ssl
from pathlib import Path
from rdflib import Graph, Namespace, RDF, RDFS, OWL
from IPython.display import display, Markdown, HTML

INS = Namespace("http://example.org/insurance#")
NOTEBOOK_DIR = Path(".").resolve()
ONTOLOGY_DIR = NOTEBOOK_DIR

# ── Ontop VKG ────────────────────────────────────────────────────────────
ONTOP_URL = None


def configure(ontop_endpoint=None, neptune_config=None):
    """Set runtime configuration. Call before using query functions.
    
    Args:
        ontop_endpoint: Ontop VKG URL (e.g. "http://internal-alb-xxx.elb.amazonaws.com")
        neptune_config: Dict from graph_notebook config (json.loads of %graph_notebook_config output)
    """
    global ONTOP_URL, NEPTUNE_HOST, NEPTUNE_PORT, NEPTUNE_REGION
    if ontop_endpoint:
        ONTOP_URL = ontop_endpoint
    if neptune_config:
        NEPTUNE_HOST = neptune_config.get("host", "")
        NEPTUNE_PORT = neptune_config.get("port", 8182)
        NEPTUNE_REGION = neptune_config.get("aws_region", NEPTUNE_REGION)

# ── Neptune ──────────────────────────────────────────────────────────────
NEPTUNE_HOST = ""
NEPTUNE_PORT = 8182
NEPTUNE_REGION = os.environ.get("AWS_REGION", "us-east-1")


# ── Graph loading ────────────────────────────────────────────────────────

def load_ontology():
    """Load the OWL ontology."""
    g = Graph()
    g.parse(str(NOTEBOOK_DIR / "ontology.ttl"))
    return g


def load_claim_data():
    """Load claim data from Ontop, falling back to local TTL."""
    if ONTOP_URL:
        try:
            g = fetch_rdf_from_ontop(ONTOP_URL)
            print(f"Loaded {len(g)} triples from Ontop ({ONTOP_URL})")
            return g, "Ontop"
        except Exception as e:
            print(f"Ontop unavailable: {e}, falling back to local data.ttl")
    g = Graph()
    g.parse(str(NOTEBOOK_DIR / "data.ttl"))
    return g, "Local (data.ttl)"


def fetch_rdf_from_ontop(endpoint_url):
    """Fetch all instance triples from Ontop via CONSTRUCT query."""
    sparql = """
    PREFIX : <http://example.org/insurance#>
    CONSTRUCT { ?s ?p ?o }
    WHERE { ?s ?p ?o . FILTER(STRSTARTS(STR(?s), STR(:))) }
    """
    url = f"{endpoint_url.rstrip('/')}/sparql"
    req = urllib.request.Request(url, data=sparql.encode("utf-8"), method="POST",
        headers={"Content-Type": "application/sparql-query", "Accept": "application/rdf+xml"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        rdf_data = resp.read()
    g = Graph()
    g.parse(data=rdf_data, format="xml")
    return g


# ── SigV4 signing for Neptune IAM auth ───────────────────────────────────

def _sigv4_request(method, url, data=None, headers=None):
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    creds = boto3.Session().get_credentials().get_frozen_credentials()
    aws_req = AWSRequest(method=method, url=url, data=data, headers=headers or {})
    SigV4Auth(creds, "neptune-db", NEPTUNE_REGION).add_auth(aws_req)
    req = urllib.request.Request(url, data=data.encode() if isinstance(data, str) else data, method=method)
    for k, v in aws_req.headers.items():
        req.add_header(k, v)
    return req


# ── SPARQL query backends ────────────────────────────────────────────────

def sparql_query(query, graph=None):
    """Run a SPARQL SELECT against Neptune, Ontop, or a local graph."""
    if NEPTUNE_HOST:
        return _neptune_query(query)
    elif ONTOP_URL:
        return ontop_query(query)
    elif graph:
        return _local_query(query, graph)
    raise RuntimeError("No query backend configured")


def _neptune_query(query):
    if "PREFIX :" not in query and ":" in query:
        query = "PREFIX : <http://example.org/insurance#>\n" + query
    url = f"https://{NEPTUNE_HOST}:{NEPTUNE_PORT}/sparql"
    body = urllib.parse.urlencode({"query": query})
    req = _sigv4_request("POST", url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/sparql-results+json"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        result = json.loads(resp.read())
    return [{k: b[k]["value"] for k in b} for b in result["results"]["bindings"]]


def neptune_update(update_query):
    """Run a SPARQL UPDATE against Neptune."""
    url = f"https://{NEPTUNE_HOST}:{NEPTUNE_PORT}/sparql"
    body = urllib.parse.urlencode({"update": update_query})
    req = _sigv4_request("POST", url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return resp.status


def ontop_query(query):
    url = f"{ONTOP_URL.rstrip('/')}/sparql"
    req = urllib.request.Request(url, data=query.encode("utf-8"), method="POST",
        headers={"Content-Type": "application/sparql-query", "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    return [{k: b[k]["value"] for k in b} for b in result["results"]["bindings"]]


def _local_query(query, graph):
    results = graph.query(query)
    return [{str(v): str(row[v]) if row[v] is not None else None for v in results.vars} for row in results]


# ── Text-to-SPARQL ──────────────────────────────────────────────────────

TEXT_TO_SPARQL_PROMPT = """You are a SPARQL query generator for an insurance claims ontology.

ONTOLOGY (namespace: http://example.org/insurance#):
  Classes: Claim, Policy, PolicyCoverage, ClaimEvent, Customer

  Claim: :claimId (string), :claimAmount (decimal), :incidentDate (dateTime), :forPolicy -> Policy, :hasEvent -> ClaimEvent
  ClaimEvent: :eventType ("submitted"|"approved"|"denied"|"paid"|"adjusted"), :eventTimestamp (dateTime), :eventAmount (decimal, optional)
  Policy: :policyId (string), :policyType ("FSA"|"HSA"|"HRA"), :heldBy -> Customer, :hasCoverage -> PolicyCoverage
  Customer: :customerId (string), :customerName (string)
  PolicyCoverage: :coverageAmount (decimal), :deductible (decimal), :premium (decimal), :validFrom (dateTime), :validTo (dateTime, optional), :isCurrent (boolean)

RULES:
- Start with: PREFIX : <http://example.org/insurance#>
- Return ONLY the SPARQL query
- Use SELECT queries only

USER QUESTION: {question}

SPARQL:"""


def text_to_sparql(question, model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0"):
    """Convert natural language to SPARQL via Bedrock."""
    import boto3
    bedrock = boto3.client("bedrock-runtime", region_name=NEPTUNE_REGION)
    resp = bedrock.invoke_model(modelId=model_id, body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31", "max_tokens": 500, "temperature": 0,
        "messages": [{"role": "user", "content": TEXT_TO_SPARQL_PROMPT.replace("{question}", question)}],
    }))
    sparql = json.loads(resp["body"].read())["content"][0]["text"].strip()
    # Clean up markdown code fences and extract first query only
    if "```" in sparql:
        blocks = sparql.split("```")
        for block in blocks[1:]:
            candidate = block.split("\n", 1)[-1].strip() if "\n" in block else block.strip()
            if candidate.upper().startswith("PREFIX") or candidate.upper().startswith("SELECT"):
                sparql = candidate
                break
    # If response contains multiple queries, take the first one
    if sparql.count("SELECT") > 1:
        sparql = sparql[:sparql.index("SELECT", sparql.index("SELECT") + 1)].strip()
    return sparql
