# Start

## What you'll build

In this workshop, we'll build a guardrail for AnyCompany's procurement agent. The guardrail is a hook
that runs before every tool call, in code the model has no say over, and checks each action against
rules that walk a knowledge graph in Amazon Neptune. We'll put the guard in front of the agent first,
before it has any rules, and then teach it more in each step. Each time, we send **the same order**
through it, for *40 units of Server Hardware from AnyCompany Components, for US-East.*

| Step | You add to the guard | The same order |
|---|---|---|
| Start | | the unguarded agent drafts it |
| 1 · Adding a hook before every tool call | ✏️ the hook, before every tool call | still drafted: no rules yet |
| 2 · Computing OFAC's 50 percent rule | ✏️ OFAC's 50% rule, in openCypher | blocked, for sanctions |
| 3 · Checking every rule in one report | forced labor, certification, stock | blocked, with all four reasons |
| 4 · Testing and deploying the guardrail | direct calls, pressure, Neptune down, deploy | blocked everywhere; redirected |

✏️ marks the two pieces you write. Each one has a check, and a solution you can reveal if you get
stuck or want to skip ahead.

## Open JupyterLab

1. Deploy the stack with `./deploy.sh`, as the package's `README.md` describes. When it
   finishes, it prints **NeptuneNotebookURL**.
2. Open that URL. It opens your notebook instance's page in the SageMaker AI console, where the
   status is **InService**. Choose **Open JupyterLab**.
3. Open the **`workshop`** folder, then **`1 - Build the guardrail`**, and open
   **`1.1 - Adding a hook before every tool call.ipynb`**.
4. **From here, stay in JupyterLab.** Every notebook has what you need to run it. The pages of
   this guide add background, if you want more.

> **Check.**
>
> JupyterLab shows the `workshop` folder, and `1.1 - Adding a hook before every tool call.ipynb` is open.

<details>
<summary>No notebook instance, or it isn't InService?</summary>

Check the stack's status in the CloudFormation console, and the Troubleshooting section of the package's `README.md`. The instance loads the graph when it starts; if it has only just started, give
it a few minutes.

</details>
