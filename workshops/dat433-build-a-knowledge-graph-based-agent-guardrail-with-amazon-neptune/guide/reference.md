# FAQ and cheat sheet

# FAQ and cheat sheet

Keep this open in a second tab while you work through the notebooks.

## Abbreviations

| Term | Stands for |
|---|---|
| **OFAC** | the Office of Foreign Assets Control, the U.S. Treasury office that publishes the sanctions list and the 50 Percent Rule |
| **SDN** | the Specially Designated Nationals list, OFAC's main sanctions list |
| **UFLPA** | the Uyghur Forced Labor Prevention Act, a U.S. law that bars goods made even in part by a company on its Entity List |
| **NIST SP 800-171** | Special Publication 800-171 of the National Institute of Standards and Technology, the U.S. standard for protecting controlled unclassified information, which U.S. federal contracts require of suppliers |
| **PO** | a purchase order |
| **MCP** | the Model Context Protocol, which lets one agent call another system's tools |
| **SHACL** | the Shapes Constraint Language, a W3C standard for validating graph data |

## FAQ

**Why use an LLM at all, if the graph decides?**
The LLM and the graph handle two different jobs. The model handles the open-ended part, which is
reading a messy request (an email, a renewal note, "Sarah already approved it") and turning it into a
specific action with a supplier, product and region. The graph handles the part that has to be exactly
right, which is whether that action is allowed. The design does not trust the model to *decide*
whether to check, because tool use is prompt-dependent and inconsistent. The agent therefore has no
verification tool; instead, a hook runs the validation query before every consequential tool call,
whatever path the model took to get there.

**Why a hook rather than a "verify" tool the agent must call first?**
A tool the agent must call is still the agent's choice, and a model under pressure can skip
it. The hook sits in the agent framework's execution path, so it runs even when a tool is
called directly with no model involved. Cell 1.2 tests your hook that way, and Cells 4.1
and 4.3 call the PO tool directly, with no model, and show that only the hook blocks it.

**Why are the walks unbounded (`*1..`) rather than a fixed number of hops?**
Because the depth isn't known in advance, which is the point of the rules, and because we know this
dataset. Its deepest chain is eight ownership hops, every walk starts from one supplier, and openCypher
never follows the same relationship twice within a path, so the walks end and stay small. In
production, an unbounded walk's cost depends on the data, and a densely connected stretch of graph,
such as many companies with cross-holdings, can multiply the paths one check explores. Consider an
upper bound (`*1..N`) chosen from the depth of your own data, and check that depth whenever you load
ownership or supply-chain data. A bound changes the answer for any chain deeper than N, so also
decide what the guard does when a chain reaches it, for example by blocking the action as
unverifiable. The 50% rule itself isn't a walk. It runs in rounds until nothing changes, so it has no
depth limit.

**Isn't this the same as Amazon Bedrock Guardrails?**
No, and they work well together. Bedrock Guardrails screens content, denied topics, PII,
and grounding against text you provide. It has no knowledge of the supplier registry and
cannot know that a parent company is sanctioned. The guardrail we build in this workshop screens
business *facts* against a knowledge graph, and production agents typically use both.

**Does what I write actually run in the deployed agent?**
Yes. Cell 4.4 packages your hook (`neptune_guard.py`) with `guard_rules.py`, `violations.cypher`
and `recommend.cypher` (given), and deploys them to Amazon Bedrock AgentCore Runtime. Your 50%
rule's results are already in the graph the deployed agent reads. It's the same agent you test in
the notebook, running your hook, plus anything you wrote in Go deeper. Kiro's MCP server
(Cell K.2) ships the same files.

**Which parts are real, and why is the registry synthetic?**
The rules are real, and so is the code that applies them. The 50% rule follows OFAC's
[FAQs 398, 399 and 401](https://ofac.treasury.gov/faqs/topic/1521), and Cell 2.4 tests it on OFAC's
own examples. The forced-labor rule follows the
[UFLPA](https://www.cbp.gov/trade/forced-labor/UFLPA), and the certification rule uses
[NIST SP 800-171](https://csrc.nist.gov/pubs/sp/800/171/r3/final), which U.S. federal contracts
require of suppliers. The companies, stakes, supply chains and stock are synthetic, for three
reasons. The 50% rule needs ownership stakes, and no regulator publishes them, because the SDN list
names who is blocked but not who owns whom. In production, the stakes come from ownership data
licensed from commercial providers, which a workshop can't redistribute. A story that ends in
sanctions and forced-labor findings would also be a factual claim about any real company we put in
it. Finally, a fixed dataset gives every attendee the same answer to check against. Cells G.7 and
G.8 in Go deeper land OFAC's real SDN list in Amazon S3, the first step of ingesting it.

**Why doesn't the guard look up the regulations in real time?**
There's nothing to look up. No regulator offers an API that answers "is this supplier blocked?",
and it couldn't, because a company blocked under the 50% rule isn't on any list, and the answer has
to be computed from ownership. Calling an external service at action time would also add a point of
failure to every action the agent takes. Production guards follow the pattern in this workshop
instead. They download the official lists on a schedule, join them with licensed ownership and
supply-chain data, recompute the derived rules when any input changes, and read the stored result
at action time. When the stored result is older than the latest list, the guard fails closed.

| Input | Who publishes it | Where |
|---|---|---|
| SDN list | OFAC, U.S. Treasury | [Sanctions List Service](https://sanctionslist.ofac.treas.gov/), as CSV and XML files |
| SDN list together with other U.S. export and sanctions lists | the Commerce, State and Treasury Departments, combined by the International Trade Administration | [Consolidated Screening List](https://www.trade.gov/consolidated-screening-list), as a download or an API |
| UFLPA Entity List | DHS, for the Forced Labor Enforcement Task Force | [a web page](https://www.dhs.gov/uflpa-entity-list) and Federal Register notices, and not part of the Consolidated Screening List |
| Ownership stakes | nobody, as public data | licensed from commercial ownership-data providers |
| Supply-chain tiers | the suppliers, and trade records | supplier declarations, and licensed supply-chain mapping data |
| Rule settings (the 50% threshold, the UFLPA's U.S. scope) | your compliance team, from the regulations | a reviewed config file that ships with the queries, here `queries/rule_settings.json` |
| Raw downloads of every list | your ingest pipeline | Amazon S3, one dated snapshot per download, as Go deeper G.7 does |
| Supplier certifications | the suppliers | their attestations, such as the NIST SP 800-171 scores that defense contractors post to the U.S. government's Supplier Performance Risk System |

**Is this really how sanctions ownership works?**
It follows OFAC's 50 Percent Rule as OFAC defines it. An entity owned 50% or more in the
aggregate, directly or indirectly, by blocked persons is itself blocked (FAQ 399 aggregates
across blocked persons and programs), and indirect ownership counts only through entities
that are themselves blocked (FAQ 401). It covers ownership, not control (FAQ 398), and
OFAC advises caution with minority stakes, which is the warning severity. EU and UK regimes
use their own tests and are not modelled. It is a teaching model, not legal advice.

**What does "ACE" mean here?**
ACE stands for Accuracy, Consistency and Explainability. The decision comes from the authoritative
graph, the same rules give the same verdict every time, and every block carries its evidence. These
are the reasons to put a knowledge graph under an agent that takes business actions.

**What is the UFLPA rule?**
The Uyghur Forced Labor Prevention Act presumes that goods produced "wholly or in part" by an
entity on the UFLPA Entity List are prohibited from import into the United States. "In part"
means any tier of the supply chain, so the rule walks `SOURCES_FROM` to any depth, and it
applies only to U.S. deliveries, so AnyCompany Devices is blocked for US-East and permitted for EU-Central.
The workshop models sourcing from company to company, while real tracing goes down to products and
components.

**Why are warehouses in the graph, but not the stock counts?**
"Who can deliver 40 units fastest?" requires knowing which warehouses carry the product and how
far each is from the delivery region. That is relationship data that changes slowly, so it lives
in the graph.
The counts change all day, across about 240,000 warehouse and product pairs, and
already have a system of record, so they live in a DynamoDB table and are read by key for the
candidates the graph returns. Cell G.5 in Go deeper changes one item, and the ranking changes while
the graph doesn't.

**OFAC changes its list regularly. What happens then?**
The rule run records which entities were listed. If the list changes, every report fails
closed with "the sanctions list has changed" until the rule is recomputed, as Cell 3.5 shows with
a live designation. In production, the list update itself triggers the recompute.

**Why compute the rule by propagation instead of one query per supplier?**
Because "blocked" is defined in terms of owners being blocked. Each round of the query
pushes the rule one ownership level further down, and repeated until nothing changes, it reaches
the whole graph. You recompute when lists or ownership change, and the agent reads the result
at action time. If it has never run, the report blocks everything rather than passing it. Each round
starts from the vertices already marked blocked, which Neptune finds through its property index, so a
round reads the blocked owners and their edges rather than every ownership edge. At a larger scale,
the next step is semi-naive evaluation, where each round reads only the owners blocked in the round
before.

**Why a validation report instead of pass/fail?**
A first-failure check hides problems, because AnyCompany Hardware can break three rules at once. The report
lists every violation with its evidence (the ownership path, the missing certificates),
which is what the agent uses to explain a block, and what an auditor wants to see.

**Why does the guard fail closed?**
If Neptune cannot be reached and the hook lets the action through, the guardrail disappears
exactly when something is wrong. Failing closed means that when the guard cannot verify an action,
it blocks rather than passes.

## openCypher cheat sheet

For runnable versions of these, and more, open **`4 - openCypher cheat sheet.ipynb`** in the
`workshop` folder: every example runs against the workshop's graph.

| You want to... | Pattern |
|---|---|
| Match a node by property | `MATCH (n:Label {name: value})` |
| Follow a relationship out / in / either | `-[:EDGE]->` / `<-[:EDGE]-` / `-[:EDGE]-` |
| Walk a chain of unknown depth | `-[:OWNED_BY*1..]->` (unbounded; in production, consider `*1..N` with N from your data) |
| Aggregate per node, filter the result, then update | `MATCH (s:Supplier)-[:HAS_WAREHOUSE]->(w) WITH s, count(w) AS sites WHERE sites > 3 SET s.multi_site = true` |
| "All elements match" (no `all()` before engine 1.5.0.0; this workshop runs 1.4.8.0) | `size([n IN list WHERE cond]) = size(list)` |
| Keep a row when a match is missing | `OPTIONAL MATCH ...` (missing pieces come back null) |
| Filter, or exclude a pattern | `WHERE ...` / `WHERE NOT (n)-[:EDGE]->(:Label)` |
| Aggregate | `count(*)`, `count(DISTINCT n)`, `collect(x)` |
| Run a subquery once per row | `CALL { WITH s ... RETURN x }` (`ORDER BY ... LIMIT` inside applies per row) |
| Nearest match (no `shortestPath()` in Neptune) | `OPTIONAL MATCH p = ... RETURN p ORDER BY length(p) LIMIT 1`, inside `CALL {}` |
| Path as evidence | `[n IN nodes(p) \| n.name]`, hop count `length(p)` |
| Set difference of two lists | `collSubtract(required, held)` |
| See the query plan | `show_explain(oc_explain(query, mode="dynamic", **params))` |
| Draw a graph in an `%%oc` cell | return a path: `MATCH p = (...)... RETURN p` |

A scalar result (like `count(*)`) renders as a **Table**; return a path (`RETURN p`) to get
the interactive **Graph** tab.

## The data model

```
Supplier   -APPROVED_FOR {approval_status, approval_level, approved_date, expiry_date}->  Product
Supplier   -OPERATES_IN->                                                                 Region
Supplier   -OWNED_BY {share_pct}->                                                        Company
Company    -OWNED_BY {share_pct}->                                                        Company         (the ownership graph)
Company    -SANCTIONED_BY {listed_date, program}->                                        SanctionsList
Product    -REQUIRES_CERT->                                                               Certification
Region     -REQUIRES_CERT->                                                               Certification
Supplier   -HOLDS_CERT {cert_status, issued_date, expiry_date}->                          Certification
Supplier   -HAS_WAREHOUSE->                                                               Warehouse
Warehouse  -STOCKS->                                                                      Product         (counts: DynamoDB)
Warehouse  -LOCATED_IN->                                                                  Region
Region     -SHIPS_TO {transit_days}->                                                     Region
Supplier   -SOURCES_FROM->                                                                Company         (tier 1)
Company    -SOURCES_FROM->                                                                Company         (tiers 2+)
Company    -ON_LIST {listed_date}->                                                       RestrictedList
```

`OWNED_BY` and `SOURCES_FROM` each come in two forms: the first hop runs from a `Supplier` to a
`Company`, and every hop after that from a `Company` to another `Company`. Those Company-to-Company
edges chain to any length, which is why the rules walk them with `*1..`. `SHIPS_TO` is the only
edge from a `Region` to a `Region`: one hop, carrying the transit time.

Only `OWNED_BY` carries a stake: an entity can have several owners, each edge with its
`share_pct`. That is why ownership can be any depth and any shape, and why OFAC's 50 Percent Rule
(blocked owners' stakes, summed, where "blocked" depends on the level above) needs a graph.
