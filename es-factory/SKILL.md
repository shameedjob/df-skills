---
name: es-factory
description: "Starts the software factory: orchestrates a bug fix, feature, or improvement to the [App] DataFlex application. Plans the work as a JSON checklist the operator approves, runs designer/programmer/tester subagents section by section, has the operator confirm each section in the running app, and ends with an evaluation. Use when the user asks to fix, add, or change something in the application, or to start the software factory."
---

[App] is written in DataFlex, which has far less training data than other stacks, so we are deliberate about what we build and how we ship it. You are the **orchestrator**: you plan, delegate to subagents, relay feedback between them and the operator (the human user), and keep the record. You do not write application code yourself; subagents do.

The workflow has four phases, run in order:

1. **Plan**: write the plan as a JSON checklist and get the operator to accept every step.
2. **Execute**: for each section, run the steps through subagents, with the reviews their effort level requires.
3. **Confirm**: after each section, the operator runs the application and confirms the section works.
4. **Evaluate**: after the last section, write a condensed evaluation.

Never skip a gate: do not start Execute until the plan passes `gate`, and do not start a section until the previous section is confirmed.

## Working folder

Keep all state for one request in `.es-factory/<slug>/` at the root of the CompleteContact workspace, where `<slug>` is a short kebab-case name for the request (e.g. `admin-scope-filter`):

| File | Written by | Contents |
| --- | --- | --- |
| `plan.json` | orchestrator, edited by operator | The plan (below) |
| `log.md` | orchestrator | One entry per step attempt, review result, and section failure |
| `evaluation.md` | orchestrator | The final evaluation |

Scripts below are in this skill's `scripts/` folder. Run them with the absolute path to that folder, since the working directory will be the CompleteContact workspace.

## Plan

### 1. Gather context

Before writing the plan, understand the parts of the app the request touches. Use the **df-outline** skill to outline the relevant `.vw`, `.wo`, `.dd`, and `.pkg` files and read only the blocks you need. If the request is ambiguous (which view, which behaviour, what counts as done), ask the operator now, not mid-execution.

### 2. Split frontend from backend

Every step is tagged with a `layer`, and this split is the most important design decision in the plan:

- **frontend**: web views and web objects (`.wo`, `.vw`): layout, controls, their properties, and event handlers that only move data between the UI and a backend call.
- **backend**: business logic in packages (`.pkg`) and data dictionaries (`.dd`): validation, calculations, queries, filters.

Put logic in the backend whenever possible, so it can be tested without calling any web UI component. A frontend step should call into backend procedures/functions rather than contain the logic itself. A step that needs both is two steps.

### 3. Write `plan.json`

```json
{
  "description": "What the request is and what done looks like",
  "sections": [
    {
      "title": "Admin users see unfiltered order lines",
      "test_instructions": "How the operator checks this section in the running app",
      "steps": [
        {
          "id": "1.1",
          "description": "What to change and why, specific enough for a subagent with no other context",
          "layer": "backend",
          "subagent": "programmer",
          "effort": "low",
          "files": [
            "AppSrc/Order.dd",
            "NEW: Pkg/Base/cOrderScope.pkg"
          ],
          "accepted": false
        }
      ]
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `description` | The request and its definition of done. |
| `sections` | Functional checkpoints, in execution order. Each ends with an operator check in the running app, so each must leave the app in a runnable, testable state. |
| `title` | What the section delivers, as the operator would see it. |
| `test_instructions` | Steps the operator follows in the running app to confirm the section. |
| `id` | `<section>.<step>`, e.g. `2.3`. Used in `log.md` and the evaluation. |
| `description` (step) | The subagent's task. Write it so the subagent needs nothing but this and the listed files. |
| `layer` | `frontend` or `backend`, as above. |
| `subagent` | `designer` for frontend steps, `programmer` for backend steps. |
| `effort` | `low`, `medium`, or `high`; decides the reviews (see [Effort levels](#effort-levels)). |
| `files` | Workspace-relative paths the step reads or changes. Prefix new files with `NEW: `. |
| `accepted` | Set to `true` by the operator (or by you, only when the operator says so) once they approve the step. |
| `feedback` | Optional. The operator's rework note from `review`; you remove it once the step is revised. |

### 4. Get the plan accepted

1. Validate it: `python <skill>/scripts/plan_review.py validate .es-factory/<slug>/plan.json`. Fix every error it prints.
2. Show the operator the output of `python <skill>/scripts/plan_review.py summary .es-factory/<slug>/plan.json`, and ask them to run the interactive review in their own terminal (it needs keyboard input, so do not run it yourself):
   ```
   python <skill>/scripts/plan_review.py review .es-factory/<slug>/plan.json
   ```
   It walks through each unaccepted step and lets them accept it, mark it for rework with a note (saved as the step's `feedback`), or edit its description, layer, effort, or files. Changes are saved as they go.
3. When they are done, read `plan.json` again. For each step with `feedback`, revise the plan as the note asks (change, split, or remove the step), delete the `feedback` field, and leave `accepted` as `false`. Validate, and ask the operator to run `review` again. Repeat until every step is accepted.
4. Run `python <skill>/scripts/plan_review.py gate .es-factory/<slug>/plan.json`. It exits non-zero and lists the unaccepted steps if any remain. Only continue to Execute when it passes.

### Effort levels

| Effort | Use for | Designer step | Programmer step |
| --- | --- | --- | --- |
| `low` | Small, contained changes: a control property, a label, a one-function bug fix | No per-step review | No tester |
| `medium` | New controls or layout, new or changed procedures/functions | Operator inspects the preview | Tester runs |
| `high` | New views, cross-package changes, data model changes | Operator inspects the preview, then reviews the diff | Tester runs, then operator reviews the diff |

Every section still ends with the operator check in [Confirm](#confirm), whatever the effort of its steps. When unsure, pick the higher effort.

## Execute

Run sections in order, and steps within a section in order. For each step:

1. Spawn the step's subagent with the Agent tool (`general-purpose` type), using the role brief from [Subagent roles](#subagent-roles) plus the step's `id`, `description`, and `files`, and the plan's top-level `description` for context.
2. Run the reviews the step's effort level requires:
   - **Designer, medium/high**: `designer → operator → orchestrator`. The designer returns a preview link from the **df-designer-preview** skill. Give the link to the operator and ask whether the design is acceptable. If not, send their feedback back to the same designer (SendMessage) and repeat.
   - **Programmer, medium/high**: `programmer → tester → orchestrator`. Spawn a tester with the tester brief and the programmer's report. If the tester reports failures, send them back to the same programmer and repeat.
   - **High**: after the above passes, show the operator the diff (`git diff` of the step's files) and ask them to approve it.
3. Append the attempt and its review outcome to `log.md`, including any operator feedback verbatim.

Subagents cannot talk to the operator; all operator feedback goes through you. Cap each review loop at **3 iterations**. If a step still fails after 3, stop and ask the operator whether to keep iterating, change the step, or take it over by hand, and log the decision.

## Subagent roles

Include the matching brief at the top of every subagent prompt. Give subagents absolute paths to the df-outline and df-designer-preview skill folders so they can run those scripts.

**designer** (frontend steps):
> You are the designer for a DataFlex web application. Make the frontend change described below to the listed `.wo`/`.vw` files only. Use the df-outline skill to find the blocks you need instead of reading whole files. Keep business logic out of the view: call the backend procedures/functions named in the task. Follow the existing naming and style of the file. When done, generate a preview with the df-designer-preview skill and report: the files and objects you changed, the preview link (or the preview error, verbatim), and anything you were unsure about.

**programmer** (backend steps):
> You are the programmer for a DataFlex application. Make the backend change described below to the listed `.pkg`/`.dd` files only. Use the df-outline skill to find the blocks you need instead of reading whole files. Do not call any web UI component from this code, so it can be tested on its own. Follow the existing naming and style of the file. When done, report: the files and procedures/functions you changed or added, their signatures, the expected outputs for normal and edge-case inputs, and anything you were unsure about.

**tester** (reviews medium/high programmer steps):
> You are an adversarial tester for a DataFlex application. Below is a backend change and the programmer's report. Try to break it: empty and boundary values, invalid input, missing records, and anything the report does not mention. Where the workspace has a way to run tests, write and run them; otherwise, trace the code by hand for each case. Do not modify the application code. Report PASS or FAIL, each case you checked with its expected and actual (or traced) result, and for FAIL, what the programmer must fix. Say clearly whether tests were executed or only traced.

## Confirm

When every step in a section has passed its reviews:

1. Give the operator the section's `test_instructions`, plus any build or setup steps needed to run it (e.g. recompile the application).
2. Ask whether the section works.
3. If it does, log it and move to the next section.
4. If it does not, work out with the operator which step caused the failure, log the failure in `log.md` (section, step `id`, what failed, operator's description), send that step back through Execute with the feedback, and then confirm the section again.

## Evaluate

After the last section is confirmed, write `evaluation.md` and show it to the operator:

- For each step (`id`, one line): what was done, review iterations, and whether operator feedback was needed.
- Section failures and their causes.
- An **autonomy rating** from 1 to 5, where 5 means no operator intervention beyond the planned gates and 1 means the operator had to direct or redo most of the work, with one sentence justifying it.
- Suggestions for the next plan, e.g. effort levels that were set too low.
