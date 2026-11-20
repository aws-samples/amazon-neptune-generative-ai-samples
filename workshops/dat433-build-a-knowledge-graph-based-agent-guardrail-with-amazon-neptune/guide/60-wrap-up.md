# Wrap-up

We'll close the session with the recipe, two templates to take with you, and a demo from Kiro.

## The recipe

Here's what we built, step by step, and how each step carries over to an agent of your own.

| Step | What we did | In your own system |
|---|---|---|
| 1 · Adding a hook before every tool call | wrote a hook before every tool call that cancels it, failing closed | one place where every rule runs, before anything that commits you; reasons as the tool result |
| 2 · Computing OFAC's 50 percent rule | OFAC's 50% rule, computed over the ownership graph | relationships of unknown depth in a graph; derived facts computed ahead |
| 3 · Checking every rule in one report | every rule as a query with evidence, in one report; stock from DynamoDB | one query per rule, returning why; counts from their system of record; stale results fail closed |
| 4 · Testing and deploying the guardrail | tested it against direct calls, pressure and an outage; deployed it | fail closed; ship the guard with the tools, so every caller goes through it |

**A rule, as a template.** Every rule has a variable-length pattern, a condition, and a row of evidence.

```cypher
MATCH (s:Supplier {name: $supplier_name})
MATCH path = (s)-[:YOUR_RELATIONSHIP*1..]->(bad)-[:ON_YOUR_LIST]->(:YourList)
WITH bad, path ORDER BY length(path) LIMIT 1
RETURN 'your-rule' AS rule, 'violation' AS severity,
       bad.name + ' is on the list' AS message, [n IN nodes(path) | n.name] AS evidence
```

**The hook, as a template** (Strands Agents).

```python
class GuardPlugin(Plugin):
    @hook
    def before_tool(self, event: BeforeToolCallEvent) -> None:
        tool, args = event.tool_use["name"], event.tool_use.get("input") or {}
        if tool not in CONSEQUENTIAL_TOOLS:
            return
        try:
            report = run_your_rules(args)
        except Exception as e:
            event.cancel_tool = f"BLOCKED: could not check ({e})"
            return
        violations = [r for r in report if r["severity"] == "violation"]
        if violations:
            event.cancel_tool = "BLOCKED: " + "; ".join(r["message"] for r in violations)
```

Together, the two templates give an agent **ACE**. **Accuracy** comes from the decision being made by
the registry rather than the prompt. **Consistency** comes from one set of rules giving the same
verdict in the notebook, the deployed agent and Kiro. **Explainability** comes from every block naming
its rules and its evidence.

## Price both sides

Not every rule needs a graph. The table compares how each of the workshop's rules would be built with a
key-value lookup, with SQL, and with a graph.

| Rule | Key-value lookup | SQL | Graph |
|---|---|---|---|
| status, approval, region | yes | a join | yes |
| certification (F3) | two lookups and a set difference in your code | a set difference over two joins | yes |
| stock counts (F4) | **yes: the system of record, read by key** (DynamoDB here) | a sum over joins | no: they change all day; the graph keeps which warehouse carries what |
| delivery time | a precomputed number per pair | joins over shipping tables | yes, a walk from warehouse to region |
| **forced labor, any tier (F2)** | no: the depth differs for every supplier | a recursive CTE | one variable-length pattern |
| **OFAC 50% rule (F1)** | no | a recursive CTE plus an aggregate per level, rerun on every list change | a propagation to a fixpoint, then a property read |
| **all four, for one order, with evidence** | a call per rule, joined in your code | a query per rule, or one very large one | one graph query, plus one key lookup for stock |

Most of the report is made up of ordinary rules, and that's fine, because they share the query, the
data and the evidence format. Fast-changing counts stay in their system of record, and are read by key
for exactly the candidates the graph returns. The graph earns its place on relationships between
relationships, and on bringing all the rules together at the moment the agent tries to act.

## Try it on your agent

To apply the same pattern to an agent of your own, we'd suggest four steps.

1. List the actions that commit your business to something, such as a PO, a payment, a sign-off or
   a message sent.
2. Put a hook on those actions, so that no caller, whether a model, a script or another agent, can
   act without the check.
3. Write each rule as a query that returns evidence rather than a yes or no. Keep counts that
   change all day in their system of record, and read them by key.
4. Make the guard fail closed, and when it blocks, redirect to an answer that passes.

The same pattern fits other domains. In finance, the question might be whether a counterparty, or
its parent, is cleared for a trade. In healthcare, it might be whether two prescriptions interact,
given a patient's history, and in legal work, whether a clause is enforceable in a jurisdiction under
a given contract version. In each case, the guardrail stays the same, and only the graph and its rules
change.

## Learn more

- [Amazon Neptune Developer Guide](https://docs.aws.amazon.com/neptune/latest/userguide/), and
  [openCypher in Neptune](https://docs.aws.amazon.com/neptune/latest/userguide/access-graph-opencypher.html)
- [Strands Agents](https://github.com/strands-agents/sdk-python), the SDK behind the hook
- [Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html),
  the content-side complement
- [Amazon Neptune generative AI samples](https://github.com/aws-samples/amazon-neptune-generative-ai-samples)

In the closing demo, Kiro, a different AI agent, places orders through an MCP server running your
files. You can try it yourself from **Finished early?**
