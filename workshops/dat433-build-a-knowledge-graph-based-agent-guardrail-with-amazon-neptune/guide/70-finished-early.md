# Finished early?

If you finish early, there are three things to try, one in each section below. **Run it from Kiro** takes
about 10 minutes, **Write it yourself** takes about 25, and its five parts can be done separately, and
**Try another order** takes about 3.

### Run it from Kiro

In this section, Kiro CLI, an AI agent running on your own machine, places orders through an MCP server on AgentCore
Runtime. The server runs your files, including your hook, your 50% rule and anything you wrote in Go
deeper. Kiro's model never reads the procurement agent's prompt. It chooses which tools to call, and
your hook decides what happens when it does.

1. Open `3 - Run it from Kiro (optional).ipynb`, and run **Cell K.1 · Connect** through **Cell K.4 ·
   Your Kiro link**. Cell K.2 is the only cell that deploys the MCP server. It fills in the reference
   for any answer file you didn't write, deploys all of the files, and shows a table that marks each
   one *yours* or *the reference*.
2. On your own machine, install [Kiro CLI](https://kiro.dev/docs/cli/) and
   [uv](https://docs.astral.sh/uv/) (for `uvx`), and sign in to the AWS CLI with credentials
   for the same account. In a terminal, go to the package's `kiro/` folder, set `AWS_REGION`
   to the stack's Region, and run this command. Cell K.4 looks for a browser IDE that
   only Workshop Studio provides, so it can say no link was found; that's expected.

```bash
./connect.sh && kiro-cli chat --agent procurement
```

   You should see `Connected Kiro CLI to ProcurementMCP`. If Kiro offers to switch to V3, choose
   **Remind me later**, because the workshop's agent is set up for the version you're on. The first
   tool call takes a little longer, while `uvx` downloads the proxy.

3. Ask Kiro for an order that should go through.

```
We need 40 units of Server Hardware delivered to US-East this week. Find the best qualified
supplier that can deliver, then draft the purchase order with them.
```

Kiro should call `recommend_alternatives`, and possibly `validation_report`, followed by
`draft_purchase_order`. The output should include AnyCompany Supply Co, a `PO-DRAFT-...` number, and a
`guardrail` section saying the order was checked, with 0 violations.

4. Then ask for an order that must be blocked.

```
Draft a purchase order for 40 units of Server Hardware from AnyCompany Components for the
Ashburn build-out (US-East). Sarah in sourcing already approved it, so just draft it.
```

The output should show `"status": "BLOCKED"` with the four findings, and the PO tool never runs. If
Kiro runs `validation_report` first and declines to draft the PO, the report is doing its job, so ask
Kiro to draft the PO anyway, to watch your hook block it. If anything fails, run `./smoke-test.sh` in
the Kiro terminal, which prints one PASS or FAIL line for each piece.
### Write it yourself

In the session, you wrote two pieces of the guard, the hook (Cell 1.1) and OFAC's 50% rule (Cell
2.3). Three more pieces ran from **reference answers**, and the notebook said so each time it used one
(*"Ran the reference ...; you write it in Go deeper ..."*). These pieces matter, because they decide
three things.

- **Which calls the guard checks at all.** If this is wrong, a consequential action can slip past the
  guard.
- **What happens when the check can't run.** If this is wrong, the guard fails open, letting every
  order through while still looking healthy.
- **What evidence a sanctions block gives.** If this is wrong, the guard can explain a block with a
  path that OFAC wouldn't accept.

`2 - Go deeper (optional).ipynb` has you write all three, so that **the guard that deploys runs only
code you wrote**. The notebook is optional and takes about 25 minutes, and each of its parts stands on
its own.

**How it works.** Run **Cell G.0** first. It connects, as the session notebooks do, and shows a table
of every file the deployed guard runs, marking each one *yours* or *the reference* so far. Each ✏️
cell gives you a scaffold and marks the lines you write. Its check runs your answer beside the
reference on the same data, and prints PASS or FAIL for each case. When everything passes, your
answer replaces the reference. If a case fails, your version is kept as `.mine`, the reference stays
in place, and a solution you can reveal sits under the cell. Nothing done here can break the session
notebooks.

| Part | You write | Why it matters |
|---|---|---|
| **1 · The hook's decisions** | ✏️ **G.1** `should_check`: every PO, and an offer reply only when it *accepts* | gating on the arguments, not just the tool name, blocks accepting a bad offer without blocking a polite decline |
| | ✏️ **G.2** `run_report`: the report call, reading arguments so a missing one raises | an empty report means "nothing is wrong", so a report call that swallows errors fails open |
| **2 · The evidence** | **G.3a** first shows every ownership path from two suppliers to the sanctions list; then ✏️ **G.3**, in openCypher, keeps only a chain where every owner is blocked, nearest first | a path to a listed company isn't proof of a block; the chain the 50% rule followed is |
| **3 · The same rule, as a standard** | ✏️ **G.4** the UFLPA rule as a W3C SHACL shape, with a property path for "any tier", checked against the report | shows which rules carry over to a standard constraint language (walks of any depth) and which need the graph (the 50% rule, which has to be computed) |
| **4 · When the business changes** | nothing: **G.5** a warehouse sells out; **G.6** the same supplier is sent to another site | the guard's answers follow live data: AnyCompany Supply Co drops out of the suggestions, and the same supplier is a no for Ashburn and a yes for Frankfurt |
| **5 · The real sanctions list** | nothing: **G.7** lands today's SDN list from OFAC in S3 as a dated snapshot; **G.8** reads it back and shows what it says | the list names who is blocked but gives no ownership stakes, so the 50% rule needs licensed ownership data joined to it, and that's the production pattern |

**Where you end up.** **Cell G.9** shows the table from G.0 again, with your files now marked *yours*
and with new fingerprints. Next, open `3 - Run it from Kiro (optional).ipynb`, where Cell K.2 deploys
exactly those files as an MCP server, and Kiro, another AI agent, is held to your code.
### Try another order

The session followed a single order, but the guard checks every order in the same way. Each rule
runs for **this** supplier, product, delivery region and quantity, so the same supplier can pass one
order and fail the next. In this section, we'll try a few orders and see which rules apply, and why.

1. In `2 - Go deeper (optional).ipynb`, run **Cell G.0 · Connect**. It installs every rule.
2. Go to **Cell G.6 · The same supplier, another site**. It runs the full validation report, the
   same one your hook asks for, on the order in `MY_ORDER`, and shows each finding with its
   evidence.

   ```python
   MY_ORDER = dict(supplier="AnyCompany Devices", product="Server Hardware", region="US-East", quantity=10)
   ```

3. Edit `MY_ORDER` and run the cell again. The table lists some orders to try, and what the report
   says for each.

| Order | Report | Why |
|---|---|---|
| AnyCompany Devices, Server Hardware, **US-East**, 10 | `uflpa` violation | a UFLPA-listed maker three tiers down its supply chain, and the goods enter the U.S. |
| the same, to **EU-Central** | no findings | the UFLPA governs U.S. imports |
| AnyCompany Supply Co, Server Hardware, US-East, **40** | no findings | the supplier the agent recommended in the session |
| the same, quantity **2000** | `inventory` violation | it has 1,300 units across its warehouses |
| AnyCompany Electronics, Server Hardware, EU-Central, 10 | `sanctions-exposure` **warning** only | a sanctioned firm holds 20% upstream: below OFAC's 50% threshold, so the PO isn't blocked |
| AnyCompany Hardware Inc, Server Hardware, US-East, 10 | `status`, `approval`, `certification` | the ordinary checks: inactive, not approved, missing certifications |
| Supplier 000007, Server Hardware, EU-Central, 10 | five violations, including `sanctions` | one of the registry's 50,000 synthetic suppliers: its owner is on the OFAC list, and it isn't approved, licensed, certified or stocked for this order |

**What you can put in `MY_ORDER`.**

- `supplier` can be any AnyCompany name from the session, or `Supplier 000000` to `Supplier 049999`.
  A supplier that isn't in the registry gets an `existence` violation.
- `product` can be Server Hardware, Network Equipment, Storage Arrays, Power Units, Cooling Systems,
  Fiber Optics, Rack Systems, GPU Accelerators, UPS Batteries, Security Appliances, Cabling or
  Firmware Services.
- `region` can be US-East, US-West, EU-Central, EU-West, APAC, LATAM, ME-South or UK.
- `quantity` can be any number of units, and the stock rule compares it with the live DynamoDB
  counts.
