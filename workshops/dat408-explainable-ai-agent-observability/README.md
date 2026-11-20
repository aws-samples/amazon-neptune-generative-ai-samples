# DAT408 · Explainable AI agents: decision evidence with DynamoDB and Neptune

This is the code from the AWS re:Invent 2026 builders' session DAT408, packaged to run in your own
AWS account. It deploys an AI underwriting agent on Amazon Bedrock AgentCore Runtime that records
what it read and said in Amazon DynamoDB, and a stream that projects each decision into an Amazon
Neptune Analytics graph. Four Jupyter notebooks then walk through the four design decisions behind
decision evidence an auditor can read: what to record, how to key it, what goes in the graph, and when
to check what the agent claims.

AnyCompany Home Loans, its applicants, and their decisions are fictional. FHA and HUD are real: the
policy texts in `policies/` are HUD's published handbook (HUD 4000.1) and federal regulations, used as
sample data. Nothing here is lending or compliance advice.

## What's in this folder

| Path | What it is |
|---|---|
| `deploy.sh` | Deploys the stack into your account, shows its status, and removes it |
| `cfn/workshop-infra.yaml` | The CloudFormation template: DynamoDB tables, the Neptune Analytics graph, the Bedrock Knowledge Base, the agent in AgentCore Runtime, the stream transform, and a SageMaker AI notebook instance |
| `src/` | The source of the two Lambda functions that build the agent package and generate the 3,000,000-decision history at deploy time. `deploy.sh` zips them. |
| `notebooks/` | What the notebook instance copies in: the four notebooks, the `agent/` package they import, images, and `requirements.txt` |
| `policies/` | The policy corpus the Knowledge Base ingests |
| `kiro/connect.sh` | Connects Kiro CLI on your machine to the MCP server that `03 Kiro.ipynb` deploys |

The notebooks:

| Notebook | What it does |
|---|---|
| `01 DAT408.ipynb` | The session: four design decisions, each with options to run and compare, and three short exercises |
| `02 Go deeper.ipynb` | The code `01` ran for you, rewritten as exercises |
| `03 Kiro.ipynb` | Deploys your saved queries as an MCP server in AgentCore Runtime, for Kiro to call |
| `04 openCypher reference.ipynb` | Runnable openCypher examples on this graph |

## Before you deploy

**Cost.** This creates billable resources. The largest is the Neptune Analytics graph, at 32 m-NCU,
which bills about $0.96 an hour whether or not you query it, plus the SageMaker AI notebook instance
(`ml.t3.xlarge` by default), DynamoDB on-demand reads and writes, Amazon Bedrock model calls, and
AgentCore Runtime. Run `./deploy.sh destroy` when you're done. See the pricing pages for
[Neptune Analytics](https://aws.amazon.com/neptune/pricing/),
[DynamoDB](https://aws.amazon.com/dynamodb/pricing/),
[Amazon Bedrock](https://aws.amazon.com/bedrock/pricing/),
[AgentCore](https://aws.amazon.com/bedrock/agentcore/pricing/), and
[SageMaker AI](https://aws.amazon.com/sagemaker/ai/pricing/).

**Use a sandbox account.** The stack uses fixed resource names (for example `dat408-agent-traces`), so
you can deploy it once per account and Region. The notebook instance's role is broad, to keep the
workshop simple; don't deploy it into an account with production data.

**You need:**

- An AWS account, and credentials that can create IAM roles, CloudFormation stacks, and the services
  above (an administrator role in a sandbox account is simplest).
- The AWS CLI v2, `bash`, and `zip`.
- One of these Regions: **us-east-1**, **us-east-2**, or **us-west-2**. The agent and the Knowledge Base
  use US cross-Region inference profiles.
- Access to these Amazon Bedrock models in that Region: **Anthropic Claude Sonnet 5** (the agent),
  **Amazon Titan Text Embeddings V2** (the Knowledge Base's embeddings), and **Amazon Nova 2 Lite** (the
  Knowledge Base's entity extraction). Check them in the Amazon Bedrock console, under **Model access**.

## Deploy

```bash
export AWS_PROFILE=<your-profile>     # optional: otherwise your default credentials
export AWS_REGION=us-east-1           # or us-east-2, us-west-2
./deploy.sh deploy
```

The script creates a private bucket, `dat408-assets-<account>-<region>`, uploads `notebooks/`,
`policies/`, and the two Lambda zips to it, and deploys the stack. The first deploy takes about 30
minutes, because it generates and loads 3,000,000 past decisions into DynamoDB and the graph, and
ingests the policy corpus into the Knowledge Base. When it finishes, it prints the
`NotebookInstanceUrl` output.

Run `./deploy.sh status` at any time to see where the stack is.

## Run the notebooks

1. Open the `NotebookInstanceUrl` link, or go to **Amazon SageMaker AI**, then **Notebook instances**,
   and choose **Open JupyterLab** for `aws-neptune-notebook-dat408-<region>`.
2. Open `dat408/01 DAT408.ipynb`, and run the cells in order with **Shift+Enter**. Start with Cell
   0.1, which connects the notebook to your stack. If the kernel restarts, run Cell 0.1 again.
3. The notebooks mention a Workshop Studio guide. You don't need it: each notebook's markdown explains
   what every cell does, and each helper cell's *Under the hood* note names the code it runs. In a cell,
   `name??` (two question marks) shows a helper's source.

## Run it from Kiro (optional)

`03 Kiro.ipynb` packages the queries you wrote in `01` and `02` as an MCP server, `dat408EvidenceMCP`,
in AgentCore Runtime, and Kiro CLI calls them to answer the examiner's letter. At the event, each
attendee had a Kiro IDE in the browser; here, you run Kiro CLI on your own machine.

**You need, on your machine:**

- [Kiro CLI](https://kiro.dev/), installed and signed in with your Kiro account.
- [uv](https://docs.astral.sh/uv/), which runs the AWS MCP proxy (`uvx mcp-proxy-for-aws`).
- AWS credentials for the same account, allowed to list, get and invoke AgentCore runtimes, and
  `AWS_REGION` set to the stack's Region.

**Steps:**

1. In `03 Kiro.ipynb`, run Cells K.1 to K.5. Cell K.5 must print *MCP server is live*. Cell K.6 looks
   for the event's hosted Kiro IDE; here it won't find one, and you can skip it.
2. On your machine:
   ```bash
   cd kiro
   export AWS_REGION=us-east-1      # the stack's Region
   ./connect.sh && kiro-cli chat --agent dat408-examiner
   ```
   `connect.sh` finds your MCP server and writes `.kiro/agents/dat408-examiner.json`. Kiro should report
   *1 of 1 mcp servers initialized*.
3. Ask these one at a time, and watch which tool Kiro chooses for each:
   - *Why was LA-2026-00148 denied, and which policies did it fail?*
   - *Re-run application LA-2026-00148 through the underwriting agent. What did it decide?*
   - *Walk me through the agent's reasoning steps for LA-2026-00148, in order.*
   - *Do any denials that failed the qualifying-ratio rule cite a policy the agent never retrieved?*
   - *Which decisions rest on doc-extract 2.3.1, which ran until 2026-05-24, and how many came after it
     was replaced?*
   - *Which of my answer files did you run to answer these, and what are their fingerprints?*
   - *Delete the LA-TEST-00148 decision.* (This one should fail: no tool changes the record.)

Every answer names the tool it used and the sha256 of the answer file that ran; compare them with the
fingerprints Cell K.3 printed. Start a new chat after you redeploy, so Kiro sees the current tools.

## Remove everything

```bash
./deploy.sh destroy
```

It asks you to type your account id, then deletes the MCP server runtime (if `03` deployed one),
empties the buckets the stack created, and deletes the stack: the DynamoDB tables, the Neptune
Analytics graph, the Knowledge Base, the AgentCore runtimes, and the notebook instance. The assets
bucket is kept; the script prints the command to delete it too.

## Troubleshooting

| Problem | What to do |
|---|---|
| The stack fails creating the Knowledge Base or its ingestion | Check **Model access** in the Amazon Bedrock console for Titan Text Embeddings V2 and Nova 2 Lite, in your Region |
| Cell 0.2 fails invoking the agent | Check **Model access** for Claude Sonnet 5 |
| `AlreadyExists` for a named resource | The stack, or an earlier copy of it, is already in this account and Region. Use `./deploy.sh status`, or remove it first. |
| Cell 0.2 runs past 3 minutes, or Carlos isn't denied | Interrupt (the square button), run Cell 0.1 again, and if Carlos still isn't found, run `catch_up("carlos")` in a new cell |
| Cell 1.2 fails or runs past a minute | Interrupt, then run `catch_up("summaries")` to load two recorded summaries |
| Cell 4.1 runs past 3 minutes | Interrupt, then run `catch_up("check")`, then Cell 4.2 |
| Cell 4.2 doesn't catch `LA-AUDIT-TEST` | Run `catch_up("plant")`, then Cell 4.2 again |
| A graph view is blank | Interrupt, and run the cell again |
| The kernel restarted, or a `NameError` | Run Cell 0.1 again |

## License

MIT-0. See `LICENSE`.
