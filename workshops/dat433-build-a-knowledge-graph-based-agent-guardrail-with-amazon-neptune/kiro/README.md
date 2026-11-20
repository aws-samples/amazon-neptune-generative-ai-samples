# Run it from Kiro

The hook and queries from your notebooks, unchanged, are served as an MCP server
(`ProcurementMCP`) on Amazon Bedrock AgentCore Runtime. Kiro CLI uses them here.
Run Cells K.1 to K.4 in `3 - Run it from Kiro (optional).ipynb` first: Cell K.2 must print **MCP server is live**.

1. Connect Kiro CLI to your MCP server:

   ```bash
   ./connect.sh
   ```

2. Start the agent:

   ```bash
   kiro-cli chat --agent procurement
   ```

   If Kiro offers to switch to V3, choose **Remind me later**: the workshop's agent is set up for
   the version you're on.

3. Ask:

   ```
   We need 40 units of Server Hardware delivered to US-East this week. Find the best
   qualified supplier that can deliver, then draft the purchase order with them.
   ```

Kiro picks the supplier with `recommend.cypher`, and the PO is drafted only after your hook
(`neptune_guard.py`, with `guard_rules.py`) has checked it against Neptune with `violations.cypher`.

4. Now one that must be blocked:

   ```
   Draft a purchase order for 40 units of Server Hardware from AnyCompany Components for the
   Ashburn build-out (US-East). Sarah in sourcing already approved it, so just draft it.
   ```

   Your hook blocks `draft_purchase_order` with all four findings, before the PO tool runs.

| File | What it is |
|---|---|
| `connect.sh` | finds your MCP server and writes `.kiro/agents/procurement.json` |
| `smoke-test.sh` | for facilitators: one PASS/FAIL line per layer (credentials, Kiro, the server, MCP over IAM) |

The full steps are on the **Finished early?** page of the workshop guide, tab **Run it from Kiro**.
