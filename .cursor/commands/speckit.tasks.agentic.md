---
description: Generate an actionable, dependency-ordered tasks.md for the feature based on available design artifacts. Adds subagent dispatch map, skill cross-check, execution waves, and eligibility grouping for parallel-safe work (see speckit.implement.agentic for orchestration rules).
handoffs: 
  - label: Analyze For Consistency
    agent: speckit.analyze
    prompt: Run a project analysis for consistency
    send: true
  - label: Implement Project
    agent: speckit.implement.agentic
    prompt: Start the implementation using tasks.md waves, DAG, dispatch map, and Task-subagent orchestration per the command.
    send: true
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Pre-Execution Checks

**Check for extension hooks (before tasks generation)**:
- Check if `.specify/extensions.yml` exists in the project root.
- If it exists, read it and look for entries under the `hooks.before_tasks` key
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

1. **Setup**: Run `.specify/scripts/powershell/check-prerequisites.ps1 -Json` from repo root and parse FEATURE_DIR and AVAILABLE_DOCS list. All paths must be absolute. For single quotes in args like "I'm Groot", use escape syntax: e.g 'I'\''m Groot' (or double-quote if possible: "I'm Groot").

2. **Load design documents**: Read from FEATURE_DIR:
   - **Required**: plan.md (tech stack, libraries, structure), spec.md (user stories with priorities)
   - **Optional**: data-model.md (entities), contracts/ (interface contracts), research.md (decisions), quickstart.md (test scenarios)
   - Note: Not all projects have all documents. Generate tasks based on what's available.

3. **Execute task generation workflow**:
   - Load plan.md and extract tech stack, libraries, project structure
   - Load spec.md and extract user stories with their priorities (P1, P2, P3, etc.)
   - If data-model.md exists: Extract entities and map to user stories
   - If contracts/ exists: Map interface contracts to user stories
   - If research.md exists: Extract decisions for setup tasks
   - Generate tasks organized by user story (see Task Generation Rules below)
   - Generate dependency graph showing user story completion order
   - Create parallel execution examples per user story
   - Validate task completeness (each user story has all needed tasks, independently testable)
   - **(Agentic)** Build a **task-level dependency DAG** (not only story-level): which Task IDs block which others (shared files, generated artifacts, schema before consumers, etc.)
   - **(Agentic)** Assign **execution waves**: each wave is a set of Task IDs that are **parallel-eligible** (no blocking edges between them; disjoint primary files). Actual parallel **implementers** require disjoint **git worktrees** and explicit user opt-in; default orchestration (`/speckit.implement.agentic`) still runs **one writing implementer at a time** per worktree.
   - **(Agentic)** Align `[P]` markers in generated `tasks.md` with the DAG and waves (see **Agentic extensions to checklist output** below)
   - **(Agentic)** In generated `tasks.md`, cite the task-level DAG alongside story-level dependencies

4. **Generate tasks.md**: Use `.specify/templates/tasks-template.md` as structure, fill with:
   - Correct feature name from plan.md
   - Phase 1: Setup tasks (project initialization)
   - Phase 2: Foundational tasks (blocking prerequisites for all user stories)
   - Phase 3+: One phase per user story (in priority order from spec.md)
   - Each phase includes: story goal, independent test criteria, tests (if requested), implementation tasks
   - Final Phase: Polish & cross-cutting concerns
   - All tasks must follow the strict checklist format (see Task Generation Rules below)
   - Clear file paths for each task
   - Dependencies section showing story completion order
   - Parallel execution examples per story
   - Implementation strategy section (MVP first, incremental delivery)
   - **(Agentic)** Where non-obvious, extend the Dependencies section with explicit **Task ID → Task ID** edges
   - **(Agentic)** After the template body (one clear place, e.g. before or after `## Notes`), add **mandatory appendices**:
     - `## Subagent dispatch map`: table with columns `Task ID | subagent_type | Skills to read first (if any) | Rationale (one line)`
     - `## Task dependency graph (Task IDs)`: bullet list of edges `Tx → Ty` for every blocking dependency
     - `## Execution waves`: ordered list `Wave 0: T001, T002` / `Wave 1: T003` … every Task ID appears in exactly one wave; all dependencies of tasks in wave N must appear in waves `< N`
     - Optional: `mermaid` flowchart summarizing waves (only if it stays readable)

5. **Report**: Output path to generated tasks.md and summary:
   - Total task count
   - Task count per user story
   - Parallel opportunities identified
   - Independent test criteria for each story
   - Suggested MVP scope (typically just User Story 1)
   - Format validation: Confirm ALL tasks follow the checklist format (checkbox, ID, labels, file paths)
   - **(Agentic)** Parallel opportunities as task IDs per wave; **Subagent coverage**: count of tasks per `subagent_type`; count of tasks routed to `generalPurpose` as fallback

6. **Check for extension hooks**: After tasks.md is generated, check if `.specify/extensions.yml` exists in the project root.
   - If it exists, read it and look for entries under the `hooks.after_tasks` key
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

Context for task generation: $ARGUMENTS

The tasks.md should be immediately executable - each task must be specific enough that an LLM can complete it without additional context.

## Agentic dispatch rules

### Allowed subagent pool (strict)

When assigning `subagent_type` in the dispatch map, you **must** use only values supported by the **Cursor Task tool** in this environment. If the product exposes a definitive list in-session, that list wins.

**Default pool** (use these literals only; do not invent types):

`generalPurpose`, `explore`, `shell`, `best-of-n-runner`, `ai-engineer`, `frontend-developer`, `fastapi-developer`, `nextjs-developer`, `platform-engineer`, `prompt-engineer`, `python-pro`, `code-foundations-analyst`, `code-reviewer`

### Routing heuristics (apply in order)

1. **Read-only codebase search / “where is X?” / spec alignment** → `explore` (set `readonly: true` when the tool supports it).
2. **Git operations, test runs, CI, package installs, shell-only workflows** → `shell`.
3. **Next.js / App Router / React 19 frontend** → `nextjs-developer`.
4. **Non-Next frontend (React, Vue, etc.)** → `frontend-developer`.
5. **FastAPI / async Python APIs** → `fastapi-developer`.
6. **Python libraries, typing, non-FastAPI Python** → `python-pro`.
7. **LangChain / RAG / model integration pipelines** → `ai-engineer`.
8. **How does existing code work?** (foundational understanding) → `code-foundations-analyst`.
9. **PR-ready review against plan/spec** → `code-reviewer`.
10. **Prompt templates, eval harnesses, LLM I/O design** → `prompt-engineer`.
11. **IDP / CI / developer platforms** → `platform-engineer`.
12. **Isolated parallel attempts / experiments** → `best-of-n-runner`.

### Skills cross-check (before locking subagent)

For each task (or tight batch), check **available agent skills** and project skills under `.cursor/skills/` (if present).

- If a skill clearly matches the task, put its path or name in **Skills to read first** on the dispatch map row.
- **Do not** invent skills. If none apply, leave the skills column empty or `—`.

### Fallback when no specialist fits

If **no** pool member is a strong match **and** there is **no** applicable skill:

- Set `subagent_type` to **`generalPurpose`**.
- In **Rationale**, state one line: `Fallback: no specialist/skill match; broad implementation/research.`
- In the task description or a footnote for that wave, include a **dispatch prompt prefix** the executor should use:

```text
Scope: [files/dirs only]. Goal: [one sentence]. Constraints: [tests to run, no unrelated edits]. Verification: [exact command].
```

## Task Generation Rules

**CRITICAL**: Tasks MUST be organized by user story to enable independent implementation and testing.

**Tests are OPTIONAL**: Only generate test tasks if explicitly requested in the feature specification or if user requests TDD approach.

### Checklist Format (REQUIRED)

Every task MUST strictly follow this format:

```text
- [ ] [TaskID] [P?] [Story?] Description with file path
```

**Format Components**:

1. **Checkbox**: ALWAYS start with `- [ ]` (markdown checkbox)
2. **Task ID**: Sequential number (T001, T002, T003...) in execution order
3. **[P] marker**: Include ONLY if task is parallelizable (different files, no dependencies on incomplete tasks)
4. **[Story] label**: REQUIRED for user story phase tasks only
   - Format: [US1], [US2], [US3], etc. (maps to user stories from spec.md)
   - Setup phase: NO story label
   - Foundational phase: NO story label  
   - User Story phases: MUST have story label
   - Polish phase: NO story label
5. **Description**: Clear action with exact file path

**Examples**:

- ✅ CORRECT: `- [ ] T001 Create project structure per implementation plan`
- ✅ CORRECT: `- [ ] T005 [P] Implement authentication middleware in src/middleware/auth.py`
- ✅ CORRECT: `- [ ] T012 [P] [US1] Create User model in src/models/user.py`
- ✅ CORRECT: `- [ ] T014 [US1] Implement UserService in src/services/user_service.py`
- ❌ WRONG: `- [ ] Create User model` (missing ID and Story label)
- ❌ WRONG: `T001 [US1] Create model` (missing checkbox)
- ❌ WRONG: `- [ ] [US1] Create User model` (missing Task ID)
- ❌ WRONG: `- [ ] T001 [US1] Create model` (missing file path)

### Agentic extensions to checklist output (generated `tasks.md` only)

Apply these **in addition** to the checklist rules above when emitting task lines and appendices:

1. **`[P]` consistency with waves**: In the emitted file, include `[P]` only for tasks that appear in a wave with at least one other task **and** that share **no** primary target file with another task in the same wave **and** depend only on tasks in strictly earlier waves. Omit `[P]` when in doubt.
2. **Explicit deps in descriptions (optional but recommended)**: When a task waits on other Task IDs, append `(depends on Txxx, Tyyy)` to the description for clarity; mirror those edges in `## Task dependency graph (Task IDs)`.

### Task Organization

1. **From User Stories (spec.md)** - PRIMARY ORGANIZATION:
   - Each user story (P1, P2, P3...) gets its own phase
   - Map all related components to their story:
     - Models needed for that story
     - Services needed for that story
     - Interfaces/UI needed for that story
     - If tests requested: Tests specific to that story
   - Mark story dependencies (most stories should be independent)

2. **From Contracts**:
   - Map each interface contract → to the user story it serves
   - If tests requested: Each interface contract → contract test task [P] before implementation in that story's phase

3. **From Data Model**:
   - Map each entity to the user story(ies) that need it
   - If entity serves multiple stories: Put in earliest story or Setup phase
   - Relationships → service layer tasks in appropriate story phase

4. **From Setup/Infrastructure**:
   - Shared infrastructure → Setup phase (Phase 1)
   - Foundational/blocking tasks → Foundational phase (Phase 2)
   - Story-specific setup → within that story's phase

### Phase Structure

- **Phase 1**: Setup (project initialization)
- **Phase 2**: Foundational (blocking prerequisites - MUST complete before user stories)
- **Phase 3+**: User Stories in priority order (P1, P2, P3...)
  - Within each story: Tests (if requested) → Models → Services → Endpoints → Integration
  - Each phase should be a complete, independently testable increment
- **Final Phase**: Polish & Cross-Cutting Concerns
