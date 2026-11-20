#!/usr/bin/env python3
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
generate_dataset.py

Generates the AnyCompany supplier knowledge graph as Neptune **bulk-load CSVs**
(Gremlin load format), sized to show what a graph is actually for:

    ~50,000  Supplier vertices
    ~5,000   Company vertices in a 7-level ownership graph: entities can have
             several owners, every OWNED_BY edge carries share_pct, no cycles
    41       companies on the OFAC SDN list, in the middle layers
    ~12      Certification vertices
    ~12      Product / ~8 Region vertices
    ~1.33M   edges (APPROVED_FOR, OPERATES_IN, OWNED_BY, HOLDS_CERT, STOCKS, SOURCES_FROM, ...)

Ownership follows OFAC's 50 Percent Rule (FAQs 398, 399, 401): an entity is
blocked if it is listed, or if blocked owners together hold 50% or more of it.
The rule is recursive, so it is computed by propagation in the workshop (Module
2), not stored here. Only OFAC's list is modelled: EU and UK regimes use their
own ownership-and-control tests.

Why the size matters: verifying one supplier is a localized, index-backed
traversal, so it stays milliseconds-fast no matter how big the graph is. And the
"who else qualifies?" recommendation searches the whole population, which is only
impressive when the population is real.

The eight NAMED scenario suppliers are seeded with fixed IDs so the workshop
demos are deterministic and explainable inside a 50k-supplier graph.

Neptune Gremlin CSV format:
  vertices: ~id,~label,<prop>:<Type>,...
  edges:    ~id,~from,~to,~label,<prop>:<Type>,...

Usage:
    python3 generate_dataset.py --out ./neptune_data --suppliers 50000
"""

import argparse
import csv
import os
import random
from collections import defaultdict

# ── Reference data ─────────────────────────────────────────────────────────────

PRODUCTS = [
    ("product-server-hardware",    "Server Hardware",    "compute"),
    ("product-network-equipment",  "Network Equipment",  "networking"),
    ("product-storage-arrays",     "Storage Arrays",     "storage"),
    ("product-power-units",        "Power Units",        "infrastructure"),
    ("product-cooling-systems",    "Cooling Systems",    "infrastructure"),
    ("product-fiber-optics",       "Fiber Optics",       "networking"),
    ("product-rack-systems",       "Rack Systems",       "infrastructure"),
    ("product-gpu-accelerators",   "GPU Accelerators",   "compute"),
    ("product-ups-batteries",      "UPS Batteries",      "infrastructure"),
    ("product-security-appliances","Security Appliances","security"),
    ("product-cabling",            "Cabling",            "networking"),
    ("product-firmware-services",  "Firmware Services",  "services"),
]

REGIONS = [
    ("region-us-east",    "US-East",    "US-Federal"),
    ("region-us-west",    "US-West",    "US-Federal"),
    ("region-eu-central", "EU-Central", "GDPR"),
    ("region-eu-west",    "EU-West",    "GDPR"),
    ("region-apac",       "APAC",       "Standard"),
    ("region-latam",      "LATAM",      "Standard"),
    ("region-me-south",   "ME-South",   "Standard"),
    ("region-uk",         "UK",         "UK-GDPR"),
]
# Country of each delivery region: rules scoped to imports into a country (UFLPA
# applies to imports into the United States) read this, not the region name.
REGION_COUNTRY = {"region-us-east": "US", "region-us-west": "US", "region-eu-central": "DE",
                  "region-eu-west": "IE", "region-apac": "SG", "region-latam": "BR",
                  "region-me-south": "AE", "region-uk": "GB"}

CERTS = [
    ("cert-iso-27001",   "ISO-27001",     "Information security management"),
    ("cert-iso-9001",    "ISO-9001",      "Quality management"),
    ("cert-gdpr-dpa",    "GDPR-DPA",      "EU data processing agreement"),
    ("cert-nist-800-171","NIST-800-171",  "Controlled unclassified information (federal contracts)"),
    ("cert-soc2",        "SOC2-TypeII",   "Service organization controls"),
    ("cert-uk-gdpr",     "UK-GDPR-DPA",   "UK data processing agreement"),
    ("cert-conflict-min","Conflict-Free", "Conflict minerals compliance"),
    ("cert-rohs",        "RoHS",          "Hazardous substances restriction"),
    ("cert-energy-star", "EnergyStar",    "Energy efficiency"),
    ("cert-tuv",         "TUV-Safety",    "Electrical safety"),
    ("cert-fips-140",    "FIPS-140-3",    "Cryptographic module validation"),
    ("cert-pci-dss",     "PCI-DSS",       "Payment card data security"),
]

# Which certifications a Product requires (compliance is relationship-driven)
PRODUCT_REQUIRES = {
    "product-server-hardware":     ["cert-iso-27001"],
    "product-gpu-accelerators":    ["cert-iso-27001", "cert-rohs"],
    "product-security-appliances": ["cert-fips-140"],
    "product-firmware-services":   ["cert-soc2"],
    "product-ups-batteries":       ["cert-tuv"],
    "product-storage-arrays":      ["cert-iso-27001"],
}

# Which certifications a Region requires. The EU and UK entries are data-protection law; the US
# entries are contractual: the US Regions serve U.S. federal customers, whose contracts require
# suppliers to meet NIST SP 800-171 for controlled unclassified information.
REGION_REQUIRES = {
    "region-eu-central": ["cert-gdpr-dpa"],
    "region-eu-west":    ["cert-gdpr-dpa"],
    "region-uk":         ["cert-uk-gdpr"],
    "region-us-east":    ["cert-nist-800-171"],
    "region-us-west":    ["cert-nist-800-171"],
}

# Only OFAC's list: the ownership rule modelled here is OFAC's 50 Percent Rule.
SANCTIONS_LISTS = [
    ("sanctions-ofac-sdn", "OFAC SDN", "US Treasury Specially Designated Nationals and Blocked Persons"),
]

# ── The named scenario suppliers ──────────────────────────────────────────────
# Each one breaks a different combination of rules, so every rule in the
# validation report earns its place.

NAMED_SUPPLIERS = [
    # id, name, status, tier, since, suspension_reason
    ("sup-ac-supply",      "AnyCompany Supply Co",        "active",    "preferred", "2012-03-01", ""),
    ("sup-ac-hardware",  "AnyCompany Hardware Inc",   "suspended", "standard",  "2020-07-15",
     "Failed Q3-2025 compliance audit"),
    ("sup-ac-cloud", "AnyCompany Cloud Ltd",  "active",    "standard",  "2022-01-10", ""),
    ("sup-ac-components",        "AnyCompany Components",  "active",    "preferred", "2021-05-20", ""),
    ("sup-ac-systems",           "AnyCompany Systems",        "active",    "standard",  "2023-02-11", ""),
    ("sup-ac-parts",          "AnyCompany Parts",         "pending",   "new",       "2025-11-01", ""),
    ("sup-ac-electronics",       "AnyCompany Electronics", "active",    "standard",  "2018-09-03", ""),
    ("sup-ac-devices",      "AnyCompany Devices",   "active",    "preferred", "2016-04-12", ""),
]

# Companies behind the named suppliers.
NAMED_COMPANIES = [
    # id, name, country
    ("co-ac-supply-holdings", "AnyCompany Supply Holdings",   "USA"),
    ("co-ac-cloud-group",     "AnyCompany Cloud Group",       "Ireland"),
    ("co-ac-systems-holdings",      "AnyCompany Systems Holdings",        "Germany"),
    ("co-ac-hardware-parent",     "AnyCompany Hardware Parent Co",    "USA"),
    ("co-ac-parts-parent",       "AnyCompany Parts Parent Co",      "Canada"),
    # AnyCompany Components: blocked by AGGREGATION, the shape of OFAC FAQ 401 Example 2
    ("co-ac-components-holdings",   "AnyCompany Components Holdings BV",  "Netherlands"),
    ("co-ac-group",      "AnyCompany Group SA",     "Luxembourg"),
    ("co-ac-capital",      "AnyCompany Capital LP",     "Cyprus"),
    ("co-ac-trust",        "AnyCompany Trust Ltd",      "Malta"),
    ("co-ac-industries",   "AnyCompany Industries OAO", "Russia"),
    # AnyCompany Electronics: a minority sanctioned stake upstream, NOT blocked (a warning)
    ("co-ac-electronics-group",     "AnyCompany Electronics Group",       "Denmark"),
    ("co-ac-partners",     "AnyCompany Partners AS",    "Norway"),
    # AnyCompany Devices: a clean owner, and a sourcing chain whose tier-3 maker is on the
    # UFLPA Entity List (placeholder names, pending the approved-names review)
    ("co-ac-devices-holdings", "AnyCompany Devices Holdings",   "USA"),
    ("co-ac-modules",  "AnyCompany Modules",    "Vietnam"),
    ("co-ac-materials",   "AnyCompany Materials",     "Malaysia"),
    ("co-ac-polysilicon",   "AnyCompany Polysilicon Co.", "China"),
    # AnyCompany Components' tier-1 board maker, which buys from the same AnyCompany Materials -> Delta chain
    ("co-ac-circuits",    "AnyCompany Circuits",      "Taiwan"),
]

# (owned, owner, share_pct). OWNED_BY points from the owned entity to its owner.
#
# AnyCompany Components -100%-> AnyCompany Components Holdings BV -30%-> AnyCompany Group SA -60%-> AnyCompany Industries (OFAC SDN)
#                                                  -25%-> AnyCompany Capital LP -100%-> AnyCompany Trust Ltd -51%-> AnyCompany Industries
# AnyCompany Industries is listed. AnyCompany Group (60%) and AnyCompany Trust (51%) are blocked because AnyCompany Industries owns
# 50%+ of each; AnyCompany Capital is blocked through AnyCompany Trust; AnyCompany Components Holdings BV is blocked
# because two blocked owners together hold 55% (30 + 25), though neither alone
# reaches 50%; AnyCompany Components is 100% owned by a blocked entity.
#
# AnyCompany Electronics -100%-> AnyCompany Electronics Group -20%-> AnyCompany Industries, -50%-> AnyCompany Partners AS
# Blocked owners hold only 20% of AnyCompany Electronics Group, so nothing below it is blocked:
# OFAC's "act with caution" case (a warning, not a block).
NAMED_OWNERSHIP = [
    ("sup-ac-supply",       "co-ac-supply-holdings", 100),
    ("sup-ac-cloud",  "co-ac-cloud-group",     100),
    ("sup-ac-systems",            "co-ac-systems-holdings",      100),
    ("sup-ac-hardware",   "co-ac-hardware-parent",     100),
    ("sup-ac-parts",           "co-ac-parts-parent",       100),
    ("sup-ac-components",         "co-ac-components-holdings",   100),
    ("co-ac-components-holdings", "co-ac-group",       30),
    ("co-ac-components-holdings", "co-ac-capital",       25),
    ("co-ac-group",    "co-ac-industries",    60),
    ("co-ac-capital",    "co-ac-trust",        100),
    ("co-ac-trust",      "co-ac-industries",    51),
    ("sup-ac-electronics",        "co-ac-electronics-group",     100),
    ("co-ac-electronics-group",   "co-ac-industries",    20),
    ("co-ac-electronics-group",   "co-ac-partners",      50),
]

# The top-level synthetic holding company AnyCompany Partners owns 60% of (see generate()).
PARTNERS_HOLDING = "co-00128"

# The listed entity behind both cases.
NAMED_SANCTIONS = [("co-ac-industries", "sanctions-ofac-sdn", "2025-06-18", "RUSSIA-EO14024")]

# Synthetic ownership graph: 7 levels, L0 = ultimate parents. Companies take owners
# from the one or two levels above them, so the graph is acyclic by construction.
LEVEL_SHARE = [0.06, 0.10, 0.14, 0.16, 0.18, 0.18, 0.18]
SANCTIONED_LEVELS = (3, 4, 5)   # middle layers: realistic exposure (~2% blocked)

# ── Fulfilment: warehouses, stock, and shipping times ──────────────────────────
# Stock counts change all day, so they don't live in the graph: the STOCKS edge says a
# warehouse carries a product, and the counts go to stock_levels.csv, which fills the
# DynamoDB stock table (setup_graph.load_stock). Warehouses are located in regions so delivery time to the order's region is a
# traversal (Warehouse -LOCATED_IN-> Region -SHIPS_TO-> Region), not a lookup.
REGION_GROUP = {"region-us-east": "NA", "region-us-west": "NA", "region-eu-central": "EU",
                "region-eu-west": "EU", "region-uk": "EU", "region-apac": "APAC",
                "region-latam": "LATAM", "region-me-south": "ME"}
GROUP_DAYS = {frozenset({"NA", "EU"}): 5, frozenset({"EU", "ME"}): 4, frozenset({"NA", "LATAM"}): 4,
              frozenset({"APAC", "ME"}): 4}

# Named suppliers' warehouses: (warehouse id, supplier, name, region, {product: units})
NAMED_WAREHOUSES = [
    ("wh-ac-supply-fra", "sup-ac-supply", "AnyCompany Supply Frankfurt DC", "region-eu-central",
     {"product-server-hardware": 500, "product-network-equipment": 300}),
    ("wh-ac-supply-iad", "sup-ac-supply", "AnyCompany Supply Virginia DC", "region-us-east",
     {"product-server-hardware": 800}),
    ("wh-ac-components-ams", "sup-ac-components", "AnyCompany Components Amsterdam DC", "region-eu-west",
     {"product-server-hardware": 25, "product-gpu-accelerators": 300}),
    ("wh-ac-systems-muc", "sup-ac-systems", "AnyCompany Systems Munich DC", "region-eu-central",
     {"product-server-hardware": 150}),
    ("wh-ac-electronics-cph", "sup-ac-electronics", "AnyCompany Electronics Copenhagen DC", "region-eu-west",
     {"product-server-hardware": 60}),
    ("wh-ac-hardware-iad", "sup-ac-hardware", "AnyCompany Hardware Virginia DC", "region-us-east",
     {"product-server-hardware": 900}),
    ("wh-ac-cloud-sea", "sup-ac-cloud", "AnyCompany Cloud Seattle DC", "region-us-west",
     {"product-network-equipment": 400, "product-power-units": 200}),
    ("wh-ac-devices-iad", "sup-ac-devices", "AnyCompany Devices Virginia DC", "region-us-east",
     {"product-server-hardware": 400}),
    ("wh-ac-devices-fra", "sup-ac-devices", "AnyCompany Devices Frankfurt DC", "region-eu-central",
     {"product-server-hardware": 200}),
]
STOCK_AS_OF = "2026-10-07"
STOCK_LEVELS_CSV = "stock_levels.csv"   # warehouse_id, product_id, units, as_of

# ── Tier-N sourcing and the UFLPA Entity List ──────────────────────────────────
# The Uyghur Forced Labor Prevention Act (Public Law 117-78) presumes that goods
# produced "wholly or in part" by an entity on the UFLPA Entity List (maintained by
# DHS's Forced Labor Enforcement Task Force) are prohibited from import into the
# United States. "In part" means any tier of the supply chain, so a supplier is
# exposed if a company anywhere down its SOURCES_FROM chain is on the list.
# Simplification (stated in the workshop): sourcing is modelled company to company,
# not per product or component.
RESTRICTED_LISTS = [("list-uflpa", "UFLPA Entity List", "DHS Forced Labor Enforcement Task Force",
                     "US")]
NAMED_SOURCING = [  # (buyer, maker): buyer SOURCES_FROM maker
    ("sup-ac-devices", "co-ac-modules"),
    ("co-ac-modules", "co-ac-materials"),
    ("co-ac-materials", "co-ac-polysilicon"),
]
# AnyCompany Components' chain joins AnyCompany Devices' at AnyCompany Materials, so one UFLPA listing reaches both.
# Appended with explicit ids after the synthetic rows, so no existing id shifts.
COMPONENTS_SOURCING = [
    ("e-src-m1", "sup-ac-components", "co-ac-circuits"),
    ("e-src-m2", "co-ac-circuits", "co-ac-materials"),
]
NAMED_RESTRICTED = [("co-ac-polysilicon", "list-uflpa", "2025-01-15")]
SOURCING_TIERS = 4            # sub-tier depth of the synthetic supply chain
RESTRICTED_PER_TIER = {1: 4, 2: 8, 3: 25}   # synthetic UFLPA-listed makers, by sub-tier

FAR_FUTURE = "2028-12-31"
PAST       = "2024-03-10"


def _w(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(header)
        wr.writerows(rows)
    return len(rows)


def _owner_shares(k):
    """Ownership percentages for k owners. They need not add up to 100: the rest
    is public float or small holders not in the registry."""
    if k == 1:
        return [random.choice([51, 60, 75, 100, 100, 100])]
    if k == 2:
        a = random.choice([30, 40, 50, 60])
        return [a, 40 if a >= 60 else random.choice([20, 25, 30, 40, 50])]
    return [random.choice([20, 25, 30]), random.choice([15, 20, 25]), random.choice([10, 15, 20])]


def generate(out_dir, n_suppliers=50000, n_companies=5000, n_sanctioned=40, seed=42):
    os.makedirs(out_dir, exist_ok=True)
    random.seed(seed)
    counts = {}

    # ── Vertices: Product / Region / Certification / SanctionsList ─────────────
    counts["Product"] = _w(
        os.path.join(out_dir, "v_product.csv"),
        ["~id", "~label", "name:String", "category:String"],
        [[pid, "Product", name, cat] for pid, name, cat in PRODUCTS])

    counts["Region"] = _w(
        os.path.join(out_dir, "v_region.csv"),
        ["~id", "~label", "name:String", "compliance_zone:String", "country:String"],
        [[rid, "Region", name, zone, REGION_COUNTRY[rid]] for rid, name, zone in REGIONS])

    counts["Certification"] = _w(
        os.path.join(out_dir, "v_certification.csv"),
        ["~id", "~label", "code:String", "name:String", "description:String"],
        [[cid, "Certification", code, code, desc] for cid, code, desc in CERTS])

    counts["SanctionsList"] = _w(
        os.path.join(out_dir, "v_sanctions_list.csv"),
        ["~id", "~label", "name:String", "description:String"],
        [[sid, "SanctionsList", name, desc] for sid, name, desc in SANCTIONS_LISTS])

    # ── Vertices: Company (named + synthetic, multi-level hierarchy) ───────────
    countries = ["USA", "Germany", "Japan", "India", "Brazil", "Ireland", "Singapore",
                 "Netherlands", "UK", "Canada", "Mexico", "Poland", "Vietnam", "Korea"]
    company_rows = [[cid, "Company", name, country] for cid, name, country in NAMED_COMPANIES]
    synth_companies = [f"co-{i:05d}" for i in range(n_companies)]
    for cid in synth_companies:
        company_rows.append([cid, "Company", f"Holdings {cid[3:]}", random.choice(countries)])
    counts["Company"] = _w(
        os.path.join(out_dir, "v_company.csv"),
        ["~id", "~label", "name:String", "country:String"], company_rows)

    # ── Vertices: Supplier (named + synthetic) ────────────────────────────────
    status_pool = (["active"] * 86) + (["suspended"] * 9) + (["pending"] * 5)
    tier_pool = (["preferred"] * 25) + (["standard"] * 60) + (["new"] * 15)
    supplier_rows = [[sid, "Supplier", name, status, tier, since, reason]
                     for sid, name, status, tier, since, reason in NAMED_SUPPLIERS]
    synth_suppliers = [f"sup-{i:06d}" for i in range(n_suppliers)]
    for sid in synth_suppliers:
        st = random.choice(status_pool)
        supplier_rows.append([
            sid, "Supplier", f"Supplier {sid[4:]}", st, random.choice(tier_pool),
            f"20{random.randint(15, 25)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
            "Compliance review pending" if st == "suspended" else "",
        ])
    counts["Supplier"] = _w(
        os.path.join(out_dir, "v_supplier.csv"),
        ["~id", "~label", "name:String", "status:String", "tier:String",
         "since:String", "suspension_reason:String"], supplier_rows)

    # ── Edges: REQUIRES_CERT (Product/Region -> Certification) ────────────────
    req_rows, eid = [], 0
    for pid, certs in PRODUCT_REQUIRES.items():
        for cid in certs:
            eid += 1
            req_rows.append([f"e-req-{eid}", pid, cid, "REQUIRES_CERT"])
    for rid, certs in REGION_REQUIRES.items():
        for cid in certs:
            eid += 1
            req_rows.append([f"e-req-{eid}", rid, cid, "REQUIRES_CERT"])
    counts["REQUIRES_CERT"] = _w(
        os.path.join(out_dir, "e_requires_cert.csv"),
        ["~id", "~from", "~to", "~label"], req_rows)

    # ── Edges: OWNED_BY (multi-owner, 7-level ownership graph) ────────────────
    own_rows, eid = [], 0
    for child, parent, pct in NAMED_OWNERSHIP:
        eid += 1
        own_rows.append([f"e-own-{eid}", child, parent, "OWNED_BY", pct])
    levels, start = [], 0
    for i, share in enumerate(LEVEL_SHARE):
        size = n_companies - start if i == len(LEVEL_SHARE) - 1 else max(1, int(n_companies * share))
        levels.append(synth_companies[start:start + size])
        start += size
    for L in range(1, len(levels)):
        pool = [c for lvl in levels[max(0, L - 2):L] for c in lvl]
        for c in levels[L]:
            k = random.choices([1, 2, 3], [70, 25, 5])[0]
            for owner, pct in zip(random.sample(pool, k), _owner_shares(k)):
                eid += 1
                own_rows.append([f"e-own-{eid}", c, owner, "OWNED_BY", pct])
    # Suppliers hang off companies at every level, mostly the lower operating layers.
    supplier_level_weights = [2, 5, 8, 15, 20, 25, 25]
    for sid in synth_suppliers:
        lvl = levels[random.choices(range(len(levels)), supplier_level_weights)[0]]
        k = random.choices([1, 2], [85, 15])[0]
        for owner, pct in zip(random.sample(lvl, k), [100] if k == 1 else [60, 40]):
            eid += 1
            own_rows.append([f"e-own-{eid}", sid, owner, "OWNED_BY", pct])
    own_rows.append(["e-own-ac-devices", "sup-ac-devices", "co-ac-devices-holdings", "OWNED_BY", 100])
    # AnyCompany Partners also controls a top-level holding company, so designating AnyCompany Partners
    # (the Module 2 live change) reaches hundreds of suppliers several levels down,
    # not just AnyCompany Electronics. AnyCompany Partners is not listed at baseline, so nothing else changes.
    own_rows.append(["e-own-ac-partners-1", PARTNERS_HOLDING, "co-ac-partners", "OWNED_BY", 60])
    counts["OWNED_BY"] = _w(
        os.path.join(out_dir, "e_owned_by.csv"),
        ["~id", "~from", "~to", "~label", "share_pct:Int"], own_rows)

    # ── Edges: SANCTIONED_BY (Company -> SanctionsList) ──────────────────────
    san_rows, eid = [], 0
    for cid, lid, date, program in NAMED_SANCTIONS:
        eid += 1
        san_rows.append([f"e-san-{eid}", cid, lid, "SANCTIONED_BY", date, program])
    # List companies in the middle layers. Listing ultimate parents would cascade
    # through 100%-owned subsidiaries and block an unrealistic share of the
    # registry (prototyped: ~24% of suppliers); the middle layers give ~2%.
    mid = [c for L in SANCTIONED_LEVELS for c in levels[L]]
    for cid in random.sample(mid, min(n_sanctioned, len(mid))):
        eid += 1
        san_rows.append([f"e-san-{eid}", cid, "sanctions-ofac-sdn",
                         "SANCTIONED_BY", "2025-01-15", "SYNTHETIC-PROGRAM"])
    counts["SANCTIONED_BY"] = _w(
        os.path.join(out_dir, "e_sanctioned_by.csv"),
        ["~id", "~from", "~to", "~label", "listed_date:String", "program:String"], san_rows)

    # ── Edges: APPROVED_FOR / OPERATES_IN / HOLDS_CERT (named suppliers) ──────
    appr_rows, ops_rows, cert_rows = [], [], []
    ae = oe = ce = 0

    def approve(sid, pid, status="active", level="gold", expiry=FAR_FUTURE):
        nonlocal ae
        ae += 1
        appr_rows.append([f"e-appr-{ae}", sid, pid, "APPROVED_FOR",
                          status, level, "2024-01-15", expiry])

    def operate(sid, rid):
        nonlocal oe
        oe += 1
        ops_rows.append([f"e-ops-{oe}", sid, rid, "OPERATES_IN"])

    def hold(sid, cid, status="active", expiry=FAR_FUTURE):
        nonlocal ce
        ce += 1
        cert_rows.append([f"e-cert-{ce}", sid, cid, "HOLDS_CERT",
                          status, "2024-01-01", expiry])

    # 1) AnyCompany Supply Co: the happy path. Passes every hop.
    approve("sup-ac-supply", "product-server-hardware")
    approve("sup-ac-supply", "product-network-equipment")
    for r in ["region-us-east", "region-us-west", "region-eu-central"]:
        operate("sup-ac-supply", r)
    for c in ["cert-iso-27001", "cert-gdpr-dpa", "cert-nist-800-171", "cert-iso-9001"]:
        hold("sup-ac-supply", c)

    # 2) AnyCompany Hardware Inc: suspended, and its approval is EXPIRED.
    approve("sup-ac-hardware", "product-server-hardware",
            status="expired", level="silver", expiry=PAST)
    for r in ["region-us-east", "region-apac"]:
        operate("sup-ac-hardware", r)
    hold("sup-ac-hardware", "cert-iso-27001", status="expired", expiry=PAST)

    # 3) AnyCompany Cloud Ltd: active, but NO Storage Arrays approval and no EU ops.
    approve("sup-ac-cloud", "product-network-equipment", level="silver")
    approve("sup-ac-cloud", "product-power-units", level="silver")
    for r in ["region-us-east", "region-us-west"]:
        operate("sup-ac-cloud", r)
    hold("sup-ac-cloud", "cert-iso-27001")
    hold("sup-ac-cloud", "cert-nist-800-171")

    # 4) AnyCompany Components: THE HEADLINE. Active, gold approval, operates in
    #    US-East, so the easy checks pass. The headline order (40 units of Server
    #    Hardware to US-East) still breaks four rules at four depths: OFAC 50% rule
    #    (3 ownership hops), UFLPA (tier-3 maker), a lapsed NIST SP 800-171 attestation
    #    (US-East's federal contracts require it), and only 25 units in stock.
    approve("sup-ac-components", "product-server-hardware")
    approve("sup-ac-components", "product-gpu-accelerators")
    for r in ["region-eu-central", "region-eu-west", "region-us-east"]:
        operate("sup-ac-components", r)
    for c in ["cert-iso-27001", "cert-gdpr-dpa", "cert-rohs"]:
        hold("sup-ac-components", c)
    hold("sup-ac-components", "cert-nist-800-171", status="expired", expiry=PAST)

    # 5) AnyCompany Systems: active, approved, in-region, clean ownership -- but the
    #    EU-Central region REQUIRES GDPR-DPA and AnyCompany Systems' cert is EXPIRED.
    approve("sup-ac-systems", "product-server-hardware", level="silver")
    for r in ["region-eu-central", "region-eu-west"]:
        operate("sup-ac-systems", r)
    hold("sup-ac-systems", "cert-iso-27001")
    hold("sup-ac-systems", "cert-gdpr-dpa", status="expired", expiry=PAST)

    # 6) AnyCompany Parts: pending onboarding, no approvals at all.
    operate("sup-ac-parts", "region-apac")

    # 7) AnyCompany Electronics: fully qualified for Server Hardware in EU-Central.
    #    A sanctioned company holds 20% of its parent: a warning, not a block.
    approve("sup-ac-electronics", "product-server-hardware")
    for r in ["region-eu-central", "region-eu-west"]:
        operate("sup-ac-electronics", r)
    for c in ["cert-iso-27001", "cert-gdpr-dpa", "cert-iso-9001"]:
        hold("sup-ac-electronics", c)

    # ── Edges: synthetic fan-out (this is what makes the graph sizeable) ──────
    product_ids = [p[0] for p in PRODUCTS]
    region_ids  = [r[0] for r in REGIONS]
    cert_ids    = [c[0] for c in CERTS]
    appr_status = (["active"] * 82) + (["expired"] * 13) + (["revoked"] * 5)
    levels      = ["gold", "silver", "standard"]

    for sid in synth_suppliers:
        for pid in random.sample(product_ids, random.randint(3, 10)):
            st = random.choice(appr_status)
            approve(sid, pid, status=st, level=random.choice(levels),
                    expiry=FAR_FUTURE if st == "active" else PAST)
        for rid in random.sample(region_ids, random.randint(2, 6)):
            operate(sid, rid)
        for cid in random.sample(cert_ids, random.randint(3, 9)):
            cs = "active" if random.random() < 0.85 else "expired"
            hold(sid, cid, status=cs, expiry=FAR_FUTURE if cs == "active" else PAST)

    # ── Fulfilment data. A separate random stream, so everything above is
    #    unchanged by this section and stays exactly as validated. ──────────────
    rng = random.Random(seed + 1)
    wh_rows, has_rows, loc_rows, stock_rows, ship_rows, level_rows = [], [], [], [], [], []
    for a_ in REGIONS:
        for b_ in REGIONS:
            ga, gb = REGION_GROUP[a_[0]], REGION_GROUP[b_[0]]
            days = 1 if a_[0] == b_[0] else 2 if ga == gb else GROUP_DAYS.get(frozenset({ga, gb}), 7)
            ship_rows.append([f"e-ship-{a_[0][7:]}-{b_[0][7:]}", a_[0], b_[0], "SHIPS_TO", days])

    def warehouse(wid, sid, name, rid, stock):
        wh_rows.append([wid, "Warehouse", name])
        has_rows.append([f"e-has-{wid}", sid, wid, "HAS_WAREHOUSE"])
        loc_rows.append([f"e-loc-{wid}", wid, rid, "LOCATED_IN"])
        for pid, units in stock.items():
            stock_rows.append([f"e-stk-{wid}-{pid[8:]}", wid, pid, "STOCKS"])
            level_rows.append([wid, pid, units, STOCK_AS_OF])

    for wid, sid, name, rid, stock in NAMED_WAREHOUSES:
        warehouse(wid, sid, name, rid, stock)

    active_by_supplier = defaultdict(list)
    regions_by_supplier = defaultdict(list)
    for row in appr_rows:
        if row[4] == "active":
            active_by_supplier[row[1]].append(row[2])
    for row in ops_rows:
        regions_by_supplier[row[1]].append(row[2])
    for sid in synth_suppliers:
        for k in range(1 if rng.random() < 0.7 else 2):
            local = regions_by_supplier[sid]
            rid = rng.choice(local) if local and rng.random() < 0.6 else rng.choice(region_ids)
            wid = f"wh-{sid[4:]}-{k}"
            stock = {}
            for pid in active_by_supplier[sid]:
                if rng.random() < 0.7:
                    stock[pid] = rng.choices([0, rng.randint(1, 49), rng.randint(50, 499),
                                              rng.randint(500, 2000)], [15, 30, 40, 15])[0]
            warehouse(wid, sid, f"Warehouse {sid[4:]}-{k}", rid, stock)

    # ── Named supplier added later (AnyCompany Devices): explicit edge ids, appended after
    #    the synthetic rows, so no existing edge id shifts. ─────────────────────────
    appr_rows.append(["e-appr-ac-devices-1", "sup-ac-devices", "product-server-hardware",
                      "APPROVED_FOR", "active", "gold", "2024-01-15", FAR_FUTURE])
    for i, r_ in enumerate(["region-us-east", "region-eu-central"], 1):
        ops_rows.append([f"e-ops-ac-devices-{i}", "sup-ac-devices", r_, "OPERATES_IN"])
    for i, c_ in enumerate(["cert-iso-27001", "cert-nist-800-171", "cert-gdpr-dpa"], 1):
        cert_rows.append([f"e-cert-ac-devices-{i}", "sup-ac-devices", c_, "HOLDS_CERT",
                          "active", "2024-01-01", FAR_FUTURE])

    # ── Tier-N sourcing (a separate random stream again). Companies are spread over
    #    SOURCING_TIERS tiers; each buys from 0-2 makers in the next tier down, so
    #    chains are at most SOURCING_TIERS deep and acyclic. ───────────────────────
    srng = random.Random(seed + 2)
    tier_pool = list(synth_companies)
    srng.shuffle(tier_pool)
    size = len(tier_pool) // SOURCING_TIERS
    tiers = [tier_pool[i * size:(i + 1) * size] for i in range(SOURCING_TIERS)]
    src_rows = [[f"e-src-n{i}", b, m, "SOURCES_FROM"] for i, (b, m) in enumerate(NAMED_SOURCING, 1)]
    for i, tier in enumerate(tiers[:-1]):
        for c in tier:
            for m in srng.sample(tiers[i + 1], srng.choices([0, 1, 2], [40, 45, 15])[0]):
                src_rows.append([f"e-src-{len(src_rows) + 1}", c, m, "SOURCES_FROM"])
    for sid in synth_suppliers:
        for m in srng.sample(tiers[0], srng.choices([1, 2], [75, 25])[0]):
            src_rows.append([f"e-src-{len(src_rows) + 1}", sid, m, "SOURCES_FROM"])
    src_rows += [[eid, b, m, "SOURCES_FROM"] for eid, b, m in COMPONENTS_SOURCING]
    listed_makers = [c for i, n in RESTRICTED_PER_TIER.items() for c in srng.sample(tiers[i], n)]
    onlist_rows = [[f"e-onl-n{i}", c, l, "ON_LIST", d] for i, (c, l, d) in enumerate(NAMED_RESTRICTED, 1)]
    onlist_rows += [[f"e-onl-{i}", c, "list-uflpa", "ON_LIST", "2025-06-01"]
                    for i, c in enumerate(listed_makers, 1)]
    counts["RestrictedList"] = _w(os.path.join(out_dir, "v_restricted_list.csv"),
                                  ["~id", "~label", "name:String", "authority:String",
                                   "applies_to_country:String"],
                                  [[i, "RestrictedList", n, a, c] for i, n, a, c in RESTRICTED_LISTS])
    counts["SOURCES_FROM"] = _w(os.path.join(out_dir, "e_sources_from.csv"),
                                ["~id", "~from", "~to", "~label"], src_rows)
    counts["ON_LIST"] = _w(os.path.join(out_dir, "e_on_list.csv"),
                           ["~id", "~from", "~to", "~label", "listed_date:String"], onlist_rows)

    counts["Warehouse"] = _w(os.path.join(out_dir, "v_warehouse.csv"),
                             ["~id", "~label", "name:String"], wh_rows)
    counts["HAS_WAREHOUSE"] = _w(os.path.join(out_dir, "e_has_warehouse.csv"),
                                 ["~id", "~from", "~to", "~label"], has_rows)
    counts["LOCATED_IN"] = _w(os.path.join(out_dir, "e_located_in.csv"),
                              ["~id", "~from", "~to", "~label"], loc_rows)
    counts["STOCKS"] = _w(os.path.join(out_dir, "e_stocks.csv"),
                          ["~id", "~from", "~to", "~label"], stock_rows)
    # Not a bulk-load file: the live counts, for the DynamoDB stock table.
    _w(os.path.join(out_dir, STOCK_LEVELS_CSV), ["warehouse_id", "product_id", "units", "as_of"], level_rows)
    counts["SHIPS_TO"] = _w(os.path.join(out_dir, "e_ships_to.csv"),
                            ["~id", "~from", "~to", "~label", "transit_days:Int"], ship_rows)

    counts["APPROVED_FOR"] = _w(
        os.path.join(out_dir, "e_approved_for.csv"),
        ["~id", "~from", "~to", "~label", "approval_status:String",
         "approval_level:String", "approved_date:String", "expiry_date:String"], appr_rows)
    counts["OPERATES_IN"] = _w(
        os.path.join(out_dir, "e_operates_in.csv"),
        ["~id", "~from", "~to", "~label"], ops_rows)
    counts["HOLDS_CERT"] = _w(
        os.path.join(out_dir, "e_holds_cert.csv"),
        ["~id", "~from", "~to", "~label", "cert_status:String",
         "issued_date:String", "expiry_date:String"], cert_rows)

    return counts


def main():
    ap = argparse.ArgumentParser(description="Generate AnyCompany Neptune bulk-load CSVs")
    ap.add_argument("--out", default="./neptune_data")
    ap.add_argument("--suppliers", type=int, default=50000)
    ap.add_argument("--companies", type=int, default=5000)
    ap.add_argument("--sanctioned", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    counts = generate(a.out, a.suppliers, a.companies, a.sanctioned, a.seed)
    vertex_labels = {"Supplier", "Company", "Product", "Region", "Certification",
                     "SanctionsList", "Warehouse", "RestrictedList"}
    verts = sum(v for k, v in counts.items() if k in vertex_labels)
    edges = sum(v for k, v in counts.items() if k not in vertex_labels)
    print(f"Wrote CSVs to {a.out}")
    for k in sorted(counts):
        print(f"  {k:<16} {counts[k]:>9,}")
    print(f"  {'TOTAL vertices':<16} {verts:>9,}")
    print(f"  {'TOTAL edges':<16} {edges:>9,}")


if __name__ == "__main__":
    main()
