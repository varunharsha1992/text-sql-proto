---
description: Execute the implementation plan by processing and executing all tasks defined in tasks.md. Adds tasks.md construct alignment (waves, DAG, dispatch map when present), Task-subagent orchestration, and inlined subagent-driven-development gates (no parallel implementer subagents on one worktree).
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Pre-Execution Checks

**Check for extension hooks (before implementation)**:
- Check if `.specify/extensions.yml` exists in the project root.
- If it exists, read it and look for entries under the `hooks.before_implement` key
- If the YAML cannot be parsed or is invalid, skip hook checking silently and continue normally
- Filter out hooks where `enabled` is explicitly `false`. Treat hooks without an `enabled` field as enabled by default.
- For each remaining hook, do **not** attempt to interpret or evaluate hook `condition` expressions:
  - If the hook has no `condition` field, or it is null/empty, treat the hook as executable
  - If the hook defines a non-empty `condition`, skip the hook and leave condition evaluation to the HookExecutor implementation
- For each executable hook, output the following based on its `optional` flag:
  - **Optional hook** (`optional: true`):
    ```
    ## Extension Hooks

    **Optional Pre-Hook**: {extension}
    Command: `/{command}`
    Description: {description}

    Prompt: {prompt}
    To execute: `/{command}`
    ```
  - **Mandatory hook** (`optional: false`):
    ```
    ## Extension Hooks

    **Automatic Pre-Hook**: {extension}
    Executing: `/{command}`
    EXECUTE_COMMAND: {command}
    
    Wait for the result of the hook command before proceeding to the Outline.
    ```
- If no hooks are registered or `.specify/extensions.yml` does not exist, skip silently

## Outline

1. Run `.specify/scripts/powershell/check-prerequisites.ps1 -Json -RequireTasks -IncludeTasks` from repo root and parse FEATURE_DIR and AVAILABLE_DOCS list. All paths must be absolute. For single quotes in args like "I'm Groot", use escape syntax: e.g 'I'\''m Groot' (or double-quote if possible: "I'm Groot").

2. **Check checklists status** (if FEATURE_DIR/checklists/ exists):
   - Scan all checklist files in the checklists/ directory
   - For each checklist, count:
     - Total items: All lines matching `- [ ]` or `- [X]` or `- [x]`
     - Completed items: Lines matching `- [X]` or `- [x]`
     - Incomplete items: Lines matching `- [ ]`
   - Create a status table:

     ```text
     | Checklist | Total | Completed | Incomplete | Status |
     |-----------|-------|-----------|------------|--------|
     | ux.md     | 12    | 12        | 0          | ✓ PASS |
     | test.md   | 8     | 5         | 3          | ✗ FAIL |
     | security.md | 6   | 6         | 0          | ✓ PASS |
     ```

   - Calculate overall status:
     - **PASS**: All checklists have 0 incomplete items
     - **FAIL**: One or more checklists have incomplete items

   - **If any checklist is incomplete**:
     - Display the table with incomplete item counts
     - **STOP** and ask: "Some checklists are incomplete. Do you want to proceed with implementation anyway? (yes/no)"
     - Wait for user response before continuing
     - If user says "no" or "wait" or "stop", halt execution
     - If user says "yes" or "proceed" or "continue", proceed to step 3

   - **If all checklists are complete**:
     - Display the table showing all checklists passed
     - Automatically proceed to step 3

3. Load and analyze the implementation context:
   - **REQUIRED**: Read tasks.md for the complete task list and execution plan
   - **REQUIRED**: Read plan.md for tech stack, architecture, and file structure
   - **IF EXISTS**: Read data-model.md for entities and relationships
   - **IF EXISTS**: Read contracts/ for API specifications and test requirements
   - **IF EXISTS**: Read research.md for technical decisions and constraints
   - **IF EXISTS**: Read quickstart.md for integration scenarios
   - **(Agentic)** If `tasks.md` defines them, extract and honor **in order**: phase headings (Setup → Foundational → User Story phases → Polish), checklist lines (`- [ ]` / `- [X]` / `Tnnn` IDs, `[P]`, `[USn]`), `## Dependencies & Execution Order`, then optional appendices `## Execution waves`, `## Task dependency graph (Task IDs)`, `## Subagent dispatch map`. **Do not** reorder or merge authored tasks unless a dependency edge explicitly requires it.

4. **Project Setup Verification**:
   - **REQUIRED**: Create/verify ignore files based on actual project setup:

   **Detection & Creation Logic**:
   - Check if the following command succeeds to determine if the repository is a git repo (create/verify .gitignore if so):

     ```sh
     git rev-parse --git-dir 2>/dev/null
     ```

   - Check if Dockerfile* exists or Docker in plan.md → create/verify .dockerignore
   - Check if .eslintrc* exists → create/verify .eslintignore
   - Check if eslint.config.* exists → ensure the config's `ignores` entries cover required patterns
   - Check if .prettierrc* exists → create/verify .prettierignore
   - Check if .npmrc or package.json exists → create/verify .npmignore (if publishing)
   - Check if terraform files (*.tf) exist → create/verify .terraformignore
   - Check if .helmignore needed (helm charts present) → create/verify .helmignore

   **If ignore file already exists**: Verify it contains essential patterns, append missing critical patterns only
   **If ignore file missing**: Create with full pattern set for detected technology

   **Common Patterns by Technology** (from plan.md tech stack):
   - **Node.js/JavaScript/TypeScript**: `node_modules/`, `dist/`, `build/`, `*.log`, `.env*`
   - **Python**: `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `dist/`, `*.egg-info/`
   - **Java**: `target/`, `*.class`, `*.jar`, `.gradle/`, `build/`
   - **C#/.NET**: `bin/`, `obj/`, `*.user`, `*.suo`, `packages/`
   - **Go**: `*.exe`, `*.test`, `vendor/`, `*.out`
   - **Ruby**: `.bundle/`, `log/`, `tmp/`, `*.gem`, `vendor/bundle/`
   - **PHP**: `vendor/`, `*.log`, `*.cache`, `*.env`
   - **Rust**: `target/`, `debug/`, `release/`, `*.rs.bk`, `*.rlib`, `*.prof*`, `.idea/`, `*.log`, `.env*`
   - **Kotlin**: `build/`, `out/`, `.gradle/`, `.idea/`, `*.class`, `*.jar`, `*.iml`, `*.log`, `.env*`
   - **C++**: `build/`, `bin/`, `obj/`, `out/`, `*.o`, `*.so`, `*.a`, `*.exe`, `*.dll`, `.idea/`, `*.log`, `.env*`
   - **C**: `build/`, `bin/`, `obj/`, `out/`, `*.o`, `*.a`, `*.so`, `*.exe`, `*.dll`, `autom4te.cache/`, `config.status`, `config.log`, `.idea/`, `*.log`, `.env*`
   - **Swift**: `.build/`, `DerivedData/`, `*.swiftpm/`, `Packages/`
   - **R**: `.Rproj.user/`, `.Rhistory`, `.RData`, `.Ruserdata`, `*.Rproj`, `packrat/`, `renv/`
   - **Universal**: `.DS_Store`, `Thumbs.db`, `*.tmp`, `*.swp`, `.vscode/`, `.idea/`

   **Tool-Specific Patterns**:
   - **Docker**: `node_modules/`, `.git/`, `Dockerfile*`, `.dockerignore`, `*.log*`, `.env*`, `coverage/`
   - **ESLint**: `node_modules/`, `dist/`, `build/`, `coverage/`, `*.min.js`
   - **Prettier**: `node_modules/`, `dist/`, `build/`, `coverage/`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`
   - **Terraform**: `.terraform/`, `*.tfstate*`, `*.tfvars`, `.terraform.lock.hcl`
   - **Kubernetes/k8s**: `*.secret.yaml`, `secrets/`, `.kube/`, `kubeconfig*`, `*.key`, `*.crt`

5. Parse tasks.md structure and extract:
   - **Task phases**: Setup, Tests, Core, Integration, Polish
   - **Task dependencies**: Sequential vs parallel execution rules
   - **Task details**: ID, description, file paths, parallel markers [P]
   - **Execution flow**: Order and dependency requirements
   - **(Agentic)** If present: parse `## Execution waves` into ordered waves of Task IDs; parse `## Task dependency graph (Task IDs)` into edges; parse `## Subagent dispatch map` rows (`Tnnn` → `subagent_type` + skills hint). Build the **effective run order**: topological order respecting waves (all deps of wave N in earlier waves) **and** phase boundaries in the file. If any of these sections are missing, fall back to phase order + `[P]` + file-based coordination only (same as `/speckit.implement`).

## Agentic orchestration (tasks.md + subagent-driven)

**Do not rely on resolving `superpowers:subagent-driven-development` by name.** Plugin skills are not guaranteed to be in context. The **canonical workflow for this command** is the inlined block below (adapted from the superpowers skill of the same name).

### Parallel execution vs `speckit.tasks.agentic` (why “parallel” can look broken)

- **`/speckit.tasks.agentic`** builds **execution waves** and **`[P]`** markers: tasks that are **dependency- and file-disjoint** so they *could* run concurrently without conflicting edits.
- **This command** intentionally requires **at most one writing implementer** subagent at a time on the **same git worktree** (avoids merge conflicts and conflicting writes). That matches the subagent-driven-development rule: *never dispatch multiple implementation subagents in parallel*.
- Cursor may still **schedule or label** subagent work as parallel at the UI level; the **orchestrator** must follow the rules here. True parallel **writers** needs **isolated branches/worktrees** (one implementer per worktree) and explicit human opt-in—otherwise treat `[P]` as **ordering/eligibility only**, not “spawn N implementers.”
- **Safe parallelism without extra worktrees**: read-only work only—for example multiple `explore` (`readonly: true`) subagents to map different areas, or background investigation. **Do not** parallelize spec vs quality review (order is fixed: spec first, then quality).

### Inlined workflow: Subagent-Driven Development (SDD)

Execute the plan by dispatching a **fresh** Task subagent per implementation task, with **two-stage review after each**: **spec compliance first**, then **code quality**. Subagents must **not** inherit your session history—paste **full task line text** + minimal scene context (feature dir, pointers to plan/spec) into each Task prompt.

**Core principle:** Fresh subagent per task + two-stage review (spec then quality) = high quality, fast iteration.

**Per implementation task (required order):**

1. Dispatch **implementer** subagent (`subagent_type` from `## Subagent dispatch map` when present; else infer from stack/paths or `generalPurpose`). Include: full `tasks.md` checklist line for this Task ID, file paths, acceptance criteria, verification commands.
2. If the implementer asks questions, answer **completely**, then re-dispatch implementer with the added context.
3. On implementer completion, dispatch **spec compliance** reviewer (e.g. `code-reviewer` or `generalPurpose` with a strict spec rubric). **Do not** start code-quality review until spec compliance is **explicitly satisfied** (re-loop implementer → spec reviewer until pass).
4. Dispatch **code quality** reviewer. Re-loop implementer → quality reviewer until pass.
5. Mark the Task ID `- [ ]` → `- [X]` in `tasks.md`. Use `TodoWrite` to track wave/task progress.
6. Only then move to the next implementation task (or next wave, still **one implementer at a time** unless human opted into multi-worktree parallel writers).

**Implementer outcomes (mandatory handling):**

- **DONE:** Proceed to spec compliance review.
- **DONE_WITH_CONCERNS:** If concerns affect correctness/scope, resolve before reviews; otherwise note and proceed.
- **NEEDS_CONTEXT:** Supply missing context; re-dispatch implementer.
- **BLOCKED:** Do not blindly retry—change context, model, split the task, or escalate to the human per blocker type.

**Model selection:** Prefer cheaper/faster models for mechanical 1–2 file tasks; standard models for integration; strongest models for architecture and for review when judgment is hard.

**Never (SDD red flags):**

- Skip **spec** or **code quality** review, or run code-quality **before** spec is **OK**.
- Dispatch **multiple implementation subagents in parallel** on the same worktree.
- Ask a subagent to “read the whole plan” without you pasting the **task-specific** text.
- Ignore implementer questions, accept “close enough” on spec compliance, skip re-review loops, or use implementer self-review **instead of** real reviews.
- Start implementation on **main/master** without explicit user consent.

**`## Subagent dispatch map`:** Use the listed `subagent_type` for the implementer; use `code-reviewer` (or equivalent) for reviewers unless the map specifies otherwise. If the map is absent, infer `subagent_type` from paths/stack or use `generalPurpose`.

**Fidelity to `tasks.md`:** Keep phase sections, goals, checkpoints, and checklist wording as authored; only update checkbox state and minimal traceability notes.

**Optional depth (not required to run this command):** Superpowers plugin skill `subagent-driven-development` and related prompts under the superpowers plugin path may add diagrams and prompt templates; treat them as supplementary.

6. Execute implementation following the task plan:
   - **Phase-by-phase execution**: Complete each phase before moving to the next
   - **Respect dependencies**: Run sequential tasks in order; **`[P]` does not override the “one writing implementer per worktree” rule** (see “Parallel execution vs `speckit.tasks.agentic`” above)
   - **Follow TDD approach**: Execute test tasks before their corresponding implementation tasks
   - **File-based coordination**: Tasks affecting the same files must run sequentially
   - **Validation checkpoints**: Verify each phase completion before proceeding
   - **(Agentic)** When `## Execution waves` exists, complete **all** tasks in Wave *k* (in effective order) before starting Wave *k+1*, subject to phase boundaries and the base rules above.
   - **(Agentic)** Within a wave, you may run **read-only** Task subagents in parallel (e.g. `explore` with `readonly: true`) for discovery; **do not** run **multiple implementers** in parallel on one worktree. For parallel **writers**, require **disjoint git worktrees** and explicit user opt-in.

7. Implementation execution rules:
   - **Setup first**: Initialize project structure, dependencies, configuration
   - **Tests before code**: If you need to write tests for contracts, entities, and integration scenarios
   - **Core development**: Implement models, services, CLI commands, endpoints
   - **Integration work**: Database connections, middleware, logging, external services
   - **Polish and validation**: Unit tests, performance optimization, documentation

8. Progress tracking and error handling:
   - Report progress after each completed task
   - Halt execution if any blocking task fails
   - When multiple **read-only** subagents were used in a wave, aggregate results; if any **implementer** failed, fix or escalate before marking the task complete
   - Provide clear error messages with context for debugging
   - Suggest next steps if implementation cannot proceed
   - **IMPORTANT** For completed tasks, make sure to mark the task off as [X] in the tasks file.
   - **(Agentic)** If using subagents: handle implementer outcomes per subagent-driven-development (e.g. NEEDS_CONTEXT, BLOCKED—re-dispatch with context/model change or split task; DONE_WITH_CONCERNS—resolve before reviews).

9. Completion validation:
   - Verify all required tasks are completed
   - Check that implemented features match the original specification
   - Validate that tests pass and coverage meets requirements
   - Confirm the implementation follows the technical plan
   - Report final status with summary of completed work

Note: This command assumes a complete task breakdown exists in tasks.md. If tasks are incomplete or missing, suggest running `/speckit.tasks` first to regenerate the task list. If you want waves, task-level edges, and a dispatch map in `tasks.md`, suggest `/speckit.tasks.agentic` instead.

10. **Check for extension hooks**: After completion validation, check if `.specify/extensions.yml` exists in the project root.
    - If it exists, read it and look for entries under the `hooks.after_implement` key
    - If the YAML cannot be parsed or is invalid, skip hook checking silently and continue normally
    - Filter out hooks where `enabled` is explicitly `false`. Treat hooks without an `enabled` field as enabled by default.
    - For each remaining hook, do **not** attempt to interpret or evaluate hook `condition` expressions:
      - If the hook has no `condition` field, or it is null/empty, treat the hook as executable
      - If the hook defines a non-empty `condition`, skip the hook and leave condition evaluation to the HookExecutor implementation
    - For each executable hook, output the following based on its `optional` flag:
      - **Optional hook** (`optional: true`):
        ```
        ## Extension Hooks

        **Optional Hook**: {extension}
        Command: `/{command}`
        Description: {description}

        Prompt: {prompt}
        To execute: `/{command}`
        ```
      - **Mandatory hook** (`optional: false`):
        ```
        ## Extension Hooks

        **Automatic Hook**: {extension}
        Executing: `/{command}`
        EXECUTE_COMMAND: {command}
        ```
    - If no hooks are registered or `.specify/extensions.yml` does not exist, skip silently
