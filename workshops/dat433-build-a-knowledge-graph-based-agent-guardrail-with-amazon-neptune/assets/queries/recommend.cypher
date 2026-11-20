// MIT No Attribution
//
// Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Permission is hereby granted, free of charge, to any person obtaining a copy of this
// software and associated documentation files (the "Software"), to deal in the Software
// without restriction, including without limitation the rights to use, copy, modify,
// merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
// permit persons to whom the Software is furnished to do so.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
// INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
// PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
// HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
// OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
// SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
//
// SPDX-License-Identifier: MIT-0

// Candidates for $product_name in $region_name: suppliers that satisfy EVERY rule, with
// the warehouses that carry the product and how many days each is from the region,
// nearest possible delivery first. Stock counts are not in the graph: they're in the
// DynamoDB stock table, and verify.recommend_alternatives reads them for these
// warehouses and keeps the suppliers that can fill the order.
// Parameters: $product_name, $region_name, $exclude ('' for none)
//
// Part 1, compliance. Required certifications are computed ONCE, before fanning
// out to candidates; the anchor is the Product, not 50,000 suppliers.
MATCH (p:Product {name: $product_name}), (r:Region {name: $region_name})
OPTIONAL MATCH (p)-[:REQUIRES_CERT]->(pc:Certification)
WITH p, r, collect(DISTINCT pc.code) AS product_certs
OPTIONAL MATCH (r)-[:REQUIRES_CERT]->(rc:Certification)
WITH p, r, product_certs + collect(DISTINCT rc.code) AS required
MATCH (p)<-[a:APPROVED_FOR {approval_status: 'active'}]-(s:Supplier {status: 'active'})-[:OPERATES_IN]->(r)
WHERE s.name <> $exclude
  AND NOT (s)-[:OWNED_BY*1..]->(:Company)-[:SANCTIONED_BY]->(:SanctionsList)
  // UFLPA: for U.S. deliveries, nothing listed at any tier of the supply chain
  AND NOT (r.country = $uflpa_country
           AND (s)-[:SOURCES_FROM*1..]->(:Company)-[:ON_LIST]->(:RestrictedList {name: $uflpa_list}))
OPTIONAL MATCH (s)-[:HOLDS_CERT {cert_status: 'active'}]->(hc:Certification)
WITH p, r, s, a, required, collect(DISTINCT hc.code) AS held
WHERE size(collSubtract(required, held)) = 0

// Part 2, fulfilment. Warehouses carry products, warehouses sit in regions, and regions
// are some number of days from the delivery region. One row per supplier: every
// warehouse that carries p and ships to r, and the nearest one's transit time.
MATCH (s)-[:HAS_WAREHOUSE]->(w:Warehouse)-[:STOCKS]->(p),
      (w)-[:LOCATED_IN]->(:Region)-[t:SHIPS_TO]->(r)
WITH s, a, p, min(t.transit_days) AS best_transit,
     collect({warehouse_id: id(w), warehouse: w.name, transit_days: t.transit_days}) AS warehouses
RETURN s.name AS supplier, s.tier AS tier, a.approval_level AS approval_level, s.since AS since,
       id(p) AS product_id, best_transit, warehouses
ORDER BY best_transit,
         CASE tier WHEN 'preferred' THEN 0 WHEN 'standard' THEN 1 ELSE 2 END,
         CASE approval_level WHEN 'gold' THEN 0 WHEN 'silver' THEN 1 ELSE 2 END,
         since, supplier
