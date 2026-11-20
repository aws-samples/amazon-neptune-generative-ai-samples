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

// One round of OFAC's 50 Percent Rule (OFAC FAQs 399 and 401).
// An entity becomes blocked when owners that are ALREADY blocked together hold
// $ofac_threshold% or more of it (50, from queries/rule_settings.json). Ownership
// through an entity that is not blocked counts for nothing (FAQ 401 Examples 4 and 5), which is why this only looks one hop up at
// owners whose blocked flag is already set.
//
// verify.apply_ownership_rule() seeds the listed companies as blocked, then runs
// this query again and again until it returns 0: each round pushes the rule one
// ownership level further down. The graph has no ownership cycles and a round only
// ever ADDS blocks, so it always terminates.
MATCH (e)-[o:OWNED_BY]->(owner)
WHERE owner.blocked = true
WITH e, sum(o.share_pct) AS blocked_share
WHERE blocked_share >= $ofac_threshold AND coalesce(e.blocked, false) = false
SET e.blocked = true, e.blocked_share = blocked_share
RETURN count(e) AS newly_blocked
