# The workshop folder

Everything for this workshop is in this folder. Open the notebooks in number order, starting with
**`1 - Build the guardrail/1.1 - Adding a hook before every tool call.ipynb`**.

```
workshop/
├── 1 - Build the guardrail/                        the session, one notebook per step:
│   ├── 1.1 - Adding a hook before every tool call.ipynb   each starts with a Connect cell
│   ├── 1.2 - Computing OFAC's 50 percent rule.ipynb
│   ├── 1.3 - Checking every rule in one report.ipynb
│   └── 1.4 - Testing and deploying the guardrail.ipynb
├── 2 - Go deeper (optional).ipynb                  write the rest of the guard yourself
├── 3 - Run it from Kiro (optional).ipynb           the same guard, from another agent
├── 4 - openCypher cheat sheet.ipynb                a reference: runnable examples on the workshop graph
├── your-guard/              the code you write, and the files the deployed guard runs
│   ├── neptune_guard.py       your hook (Cell 1.1)
│   ├── guard_rules.py         its decisions (given; you write two in Go deeper G.1 and G.2)
│   └── queries/               the rules, in openCypher
│       ├── ownership_50pct.cypher   OFAC's 50% rule (you write it in Cell 2.3)
│       ├── violations.cypher        every rule, in one report (Go deeper G.3 is yours)
│       ├── recommend.cypher         the suppliers that can deliver instead (given)
│       ├── stock_locations.cypher   which warehouses carry a product (given)
│       └── uflpa_shape.ttl          the UFLPA rule as a SHACL shape (Go deeper G.4)
└── helpers/                 given: the agent, the notebooks' helpers and the deploy code
    └── reference/             the reference answers behind the reveals and the fallbacks
```

You don't need to open anything in `your-guard/` or `helpers/` by hand. The notebook cells write
your answers into `your-guard/`, and the deploy cells ship the folder. If a check fails, your version
is kept beside the file as `.mine`, and the reference answer takes its place.

The `Neptune/` folder next to this one comes with the Neptune notebook tooling, and the workshop
doesn't use it.
