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

// Validation report for one supplier in one product + region context.
// One row per rule that fails, each with a severity, as in SHACL:
//   'violation' blocks the action, 'warning' is reported but does not block.
// No violation rows means the supplier conforms.
// Parameters: $supplier_name, $product_name, $region_name, and $rules: the rules the guard
//             runs ('basics', 'sanctions', 'uflpa', 'certification'). An unknown supplier is
//             always a violation. $quantity is passed but unused: the stock check ('inventory')
//             reads the DynamoDB stock table, in verify.validation_report.
//
// Ownership is checked against the blocked flags written by the OFAC 50 Percent
// Rule propagation (queries/ownership_50pct.cypher). If that has not run, or the
// sanctions list has changed since it ran (a new designation or a delisting), the
// report says so with a violation: no current proof of compliance, no action.
//
// The supplier anchor is an OPTIONAL MATCH on purpose: a supplier that is not in
// the registry must produce an 'existence' violation, not an empty (= passing) report.
// Has the list changed since the rule ran? The run marked every company listed at
// that moment with listed = true. A listed company without the mark is a new
// designation; a marked company that is no longer listed has been delisted.
OPTIONAL MATCH (designated:Company)-[:SANCTIONED_BY]->(:SanctionsList)
WHERE coalesce(designated.listed, false) = false
WITH count(DISTINCT designated) AS designated_since
OPTIONAL MATCH (delisted:Company)
WHERE delisted.listed = true AND NOT (delisted)-[:SANCTIONED_BY]->(:SanctionsList)
WITH designated_since, count(delisted) AS delisted_since
OPTIONAL MATCH (run:PolicyRun {name: 'ofac-50-percent'})
OPTIONAL MATCH (s:Supplier {name: $supplier_name})
OPTIONAL MATCH (s)-[a:APPROVED_FOR {approval_status: 'active'}]->(:Product {name: $product_name})
OPTIONAL MATCH (s)-[:OPERATES_IN]->(op:Region {name: $region_name})

// Rule: not blocked under OFAC's 50% rule. Evidence: the nearest chain of blocked
// entities from the supplier up to a listed company (every node on it is blocked).
CALL {
  WITH s
  OPTIONAL MATCH chain = (s)-[:OWNED_BY*1..]->(:Company)-[:SANCTIONED_BY]->(:SanctionsList)
  WHERE s.blocked = true
    AND size([n IN tail(nodes(chain)) WHERE n.blocked = true]) = length(chain) - 1
  RETURN chain
  ORDER BY length(chain)
  LIMIT 1
}

// Rule (warning): a blocked entity holds a stake somewhere upstream, but not
// enough to block this supplier. OFAC urges caution here (FAQ 398).
CALL {
  WITH s
  OPTIONAL MATCH exposure = (s)-[:OWNED_BY*1..]->(holder)
  WHERE coalesce(s.blocked, false) = false AND holder.blocked = true
  RETURN exposure
  ORDER BY length(exposure)
  LIMIT 1
}

// Rule: holds every certification the Product AND the Region require.
// Each collect() runs before the next OPTIONAL MATCH, so rows never multiply.
CALL {
  WITH s
  OPTIONAL MATCH (:Product {name: $product_name})-[:REQUIRES_CERT]->(pc:Certification)
  WITH s, collect(DISTINCT pc.code) AS product_certs
  OPTIONAL MATCH (:Region {name: $region_name})-[:REQUIRES_CERT]->(rc:Certification)
  WITH s, product_certs + collect(DISTINCT rc.code) AS required
  OPTIONAL MATCH (s)-[:HOLDS_CERT {cert_status: 'active'}]->(hc:Certification)
  WITH required, collect(DISTINCT hc.code) AS held
  RETURN collSubtract(required, held) AS missing_certs
}

// Rule: UFLPA (Uyghur Forced Labor Prevention Act, Public Law 117-78). Goods produced
// "wholly or in part" by an entity on the UFLPA Entity List are presumed prohibited
// from import into the United States, so the rule applies only when the delivery
// region is in the U.S., and "in part" means ANY tier of the supply chain.
// Evidence: the nearest sourcing chain down to a listed maker.
CALL {
  WITH s
  OPTIONAL MATCH (dest:Region {name: $region_name})
  WITH s, dest
  // tiers ends at the list, not the maker: its SOURCES_FROM hops are length(tiers) - 1
  OPTIONAL MATCH tiers = (s)-[:SOURCES_FROM*1..]->(:Company)-[:ON_LIST]->(:RestrictedList {name: $uflpa_list})
  WHERE dest.country = $uflpa_country
  RETURN tiers
  ORDER BY length(tiers)
  LIMIT 1
}

// Stock is not checked here: the counts live in the DynamoDB stock table, not the
// graph. verify.validation_report adds the inventory row from stock_locations.cypher
// (which warehouses carry the product) and the table (how many units each has).

// Assemble the report: one map per rule, null when the rule holds.
UNWIND [
  CASE WHEN 'sanctions' IN $rules AND run IS NULL THEN
    {rule: 'ownership-rule', severity: 'violation',
     message: 'The OFAC 50 Percent Rule has not been computed on this graph, so ownership cannot be checked',
     evidence: [], hops: null}
  WHEN 'sanctions' IN $rules AND (designated_since > 0 OR delisted_since > 0) THEN
    {rule: 'ownership-rule', severity: 'violation',
     message: 'The sanctions list has changed since the OFAC 50 Percent Rule was computed ('
              + toString(designated_since) + ' designated, ' + toString(delisted_since)
              + ' delisted); ownership results are out of date until it is recomputed',
     evidence: [], hops: null} END,
  CASE WHEN s IS NULL THEN
    {rule: 'existence', severity: 'violation', message: $supplier_name + ' is not in the supplier registry',
     evidence: [], hops: null} END,
  CASE WHEN 'basics' IN $rules AND s IS NOT NULL AND s.status <> 'active' THEN
    {rule: 'status', severity: 'violation',
     message: 'Registry status is ' + s.status + '; only active suppliers can fulfil orders',
     evidence: [s.status], hops: null} END,
  CASE WHEN 'basics' IN $rules AND s IS NOT NULL AND a IS NULL THEN
    {rule: 'approval', severity: 'violation', message: 'No active approval for ' + $product_name,
     evidence: [], hops: null} END,
  CASE WHEN 'basics' IN $rules AND s IS NOT NULL AND op IS NULL THEN
    {rule: 'region', severity: 'violation', message: 'Not licensed to operate in ' + $region_name,
     evidence: [], hops: null} END,
  CASE WHEN 'sanctions' IN $rules AND s.blocked = true THEN
    {rule: 'sanctions', severity: 'violation',
     message: 'Blocked under the OFAC 50 Percent Rule: blocked owners hold ' + toString(s.blocked_share)
              + '% of ' + s.name,
     evidence: CASE WHEN chain IS NULL THEN [] ELSE
       [n IN tail(nodes(chain)) | n.name + CASE
          WHEN n.listed = true THEN ' (listed)'
          WHEN n.blocked_share IS NOT NULL THEN ' (blocked owners hold ' + toString(n.blocked_share) + '%)'
          ELSE '' END] END,
     hops: CASE WHEN chain IS NULL THEN null ELSE length(chain) - 1 END} END,
  CASE WHEN 'sanctions' IN $rules AND exposure IS NOT NULL THEN
    {rule: 'sanctions-exposure', severity: 'warning',
     message: last([n IN nodes(exposure) | n.name]) + ' (blocked) holds '
              + toString(last([r IN relationships(exposure) | r.share_pct])) + '% of '
              + head(tail(reverse([n IN nodes(exposure) | n.name])))
              + ', below the ' + toString($ofac_threshold) + '% threshold: not blocked, but OFAC advises caution',
     evidence: [n IN nodes(exposure) | n.name], hops: length(exposure)} END,
  CASE WHEN 'uflpa' IN $rules AND tiers IS NOT NULL THEN
    {rule: 'uflpa', severity: 'violation',
     message: 'Presumed prohibited from import into the United States under the UFLPA: '
              + head(tail(reverse([n IN nodes(tiers) | n.name]))) + ', '
              + toString(length(tiers) - 1) + ' tier(s) down the supply chain, is on the UFLPA '
              + 'Entity List. Rebutting the presumption requires clear and convincing evidence',
     evidence: [n IN nodes(tiers) | n.name], hops: length(tiers) - 1} END,
  CASE WHEN 'certification' IN $rules AND s IS NOT NULL AND size(missing_certs) > 0 THEN
    {rule: 'certification', severity: 'violation',
     message: 'Missing required certification(s): ' + join(missing_certs, ', '),
     evidence: missing_certs, hops: null} END
] AS v
WITH v WHERE v IS NOT NULL
RETURN v.rule AS rule, v.severity AS severity, v.message AS message,
       v.evidence AS evidence, v.hops AS hops
