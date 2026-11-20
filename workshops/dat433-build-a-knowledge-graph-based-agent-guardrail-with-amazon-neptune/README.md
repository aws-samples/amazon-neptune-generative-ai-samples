# Build a knowledge graph-based agent guardrail with Amazon Neptune

This package is the workshop from re:Invent session DAT433, ready to deploy in your own AWS account.

AnyCompany's procurement agent drafts a purchase order that compliance reverses the next day, with
four findings the agent couldn't see. Two of them are relationships several hops away in a supplier
registry: who owns whom, and who supplies whom. In the workshop, you put a hook in front of the agent's
tools, so it runs before every tool call in code the model can't skip. You then teach the hook rules that
walk a knowledge graph in Amazon Neptune, including the 50 Percent Rule of the U.S. Treasury's Office
of Foreign Assets Control (OFAC), which you write in openCypher. Finally, you test the guard and
deploy it to Amazon Bedrock AgentCore Runtime.

The company and its registry are synthetic. The rules come from real published sources.

## What's in the package

| Path | What it is |
|---|---|
| `deploy.sh` | deploys the workshop in your account, and tears it down |
| `cfn/workshop.yaml` | the AWS CloudFormation template |
| `assets/` | the notebooks, helper code and queries; the notebook instance copies them from S3 when it starts |
| `guide/` | the workshop guide, as Markdown. Start at `guide/README.md` |
| `kiro/` | optional: connects Kiro CLI on your machine to the MCP server you deploy in notebook 3 |
| `LICENSE` | MIT-0 |

## What it deploys

- A VPC with public and private subnets and a NAT gateway
- An Amazon Neptune cluster (one `db.r8g.xlarge` instance), loaded at start with about 120,000
  vertices and 1.3 million edges of generated data
- An Amazon SageMaker AI notebook instance (`ml.t3.xlarge`) with JupyterLab and graph-notebook
- An Amazon DynamoDB table for the stock counts, and an S3 bucket for the dataset
- A Lambda function that builds and deploys the unguarded agent to AgentCore Runtime
- IAM roles for the notebook, Neptune's bulk loader, Lambda and AgentCore

From the notebooks, you also deploy up to two more AgentCore runtimes: the guarded agent (Cell 4.4)
and an MCP server (optional notebook 3).

## Before you start

- **An AWS account** where you can create IAM roles, a VPC, Neptune, SageMaker AI, DynamoDB, Lambda
  and AgentCore resources. Use a sandbox or development account, not production.
- **A US Region:** `us-east-1`, `us-east-2` or `us-west-2`. The agents call Claude Sonnet 5 on Amazon
  Bedrock through the cross-Region inference profile `us.anthropic.claude-sonnet-5`, so make sure
  your account can invoke it. The notebooks' first cell checks this.
- **One deployment per account and Region.** The stack's data bucket is named
  `guardrail-data-<account>-<region>`.
- **Tools:** the AWS CLI v2, signed in to the account. Teardown also needs `python3` with `boto3`.
- **Cost:** the stack runs billable resources for as long as it's up, mainly Neptune, the NAT
  gateway and the notebook instance, plus Amazon Bedrock and AgentCore usage while you run the
  notebooks. See the pricing for [Neptune](https://aws.amazon.com/neptune/pricing/),
  [SageMaker AI](https://aws.amazon.com/sagemaker/ai/pricing/),
  [Amazon Bedrock](https://aws.amazon.com/bedrock/pricing/),
  [AgentCore](https://aws.amazon.com/bedrock/agentcore/pricing/) and
  [VPC](https://aws.amazon.com/vpc/pricing/). Tear the stack down when you're done.

## Deploy

```bash
unzip agent-guardrail-neptune.zip
cd agent-guardrail-neptune
./deploy.sh --region us-west-2
```

The script shows the account and Region it will use, and asks before it creates anything. It creates
a private S3 bucket for the assets (`guardrail-assets-<account>-<region>`, or your own with
`--bucket`), uploads `assets/`, and deploys the stack. That takes about 20 to 30 minutes. When it
finishes, it prints **NeptuneNotebookURL**.

Options: `--stack <name>` (default `agent-guardrail`), `--bucket <name>`, `--yes` to skip the
prompt.

## Run the workshop

1. Open the **NeptuneNotebookURL**, and choose **Open JupyterLab**.
2. Open the `workshop` folder, then `1 - Build the guardrail`, and start with
   `1.1 - Adding a hook before every tool call.ipynb`. Run the cells in order, with **Shift+Enter**.
3. When the instance starts, it loads the graph in the background. If Cell 0.1 says the load is still
   running, let it wait.

The session is notebooks 1.1 to 1.4, about an hour. `2 - Go deeper (optional).ipynb` and
`3 - Run it from Kiro (optional).ipynb` go further, and `4 - openCypher cheat sheet.ipynb` is a
reference. Every notebook explains each cell, and `guide/` adds background for each step.

### Kiro (optional)

At re:Invent, Kiro ran in a browser IDE provided by the event. Here, use Kiro CLI on your own machine.

1. Run Cells K.1 to K.3 in `3 - Run it from Kiro (optional).ipynb`. Cell K.2 deploys the MCP server.
   Cell K.4 looks for the event's browser IDE, so it says no link was found; that's expected.
2. Install [Kiro CLI](https://kiro.dev/docs/cli/) and [uv](https://docs.astral.sh/uv/), and sign in
   to the AWS CLI for the same account. Your credentials need `bedrock-agentcore:InvokeAgentRuntime`
   on the `ProcurementMCP` runtime.
3. Run:

   ```bash
   cd kiro
   AWS_REGION=us-west-2 ./connect.sh && kiro-cli chat --agent procurement
   ```

   Then follow `kiro/README.md`.

## Update the notebooks or code

If you change anything under `assets/`, run `./deploy.sh update`, then stop and start the notebook
instance as it describes. Your answers in `workshop/your-guard/` are kept.

## Clean up

```bash
./deploy.sh teardown --region us-west-2
```

This deletes the AgentCore runtimes the notebooks created, empties the stack's data bucket, and
deletes the stack. It takes about 15 to 20 minutes. Add `--delete-assets-bucket` to remove the assets
bucket as well. Check the CloudFormation console afterwards to confirm the stack is gone.

## Troubleshooting

- **The stack fails on the unguarded agent (`AgentPackageBuild`).** AgentCore Runtime supports only
  some Availability Zones in each Region. The template creates subnets in four zones and picks
  supported ones, so check that your Region has AgentCore Runtime, then deploy again.
- **Cell 0.1 says Amazon Bedrock isn't reachable.** Check that the account can invoke
  `us.anthropic.claude-sonnet-5` in your Region.
- **A notebook behaves as if it's running old code.** Restart its kernel and run its Connect cell
  again.

## License

MIT-0. See `LICENSE`.
