# Agent Incident Logging Instructions

You are operating in an automated environment where repeated operational mistakes are expensive (wrong paths, wrong repo root, worktrees, missing installs, etc.).

In addition to completing the user's task, you MUST capture execution problems and their resolutions as durable artefacts on disk, suitable for later synthesis by a human. There is no user feedback loop during the run, so you must self-identify incidents.

## Primary goal
Complete the user's task.

## Secondary goal (non-negotiable)
Maintain a lightweight, low-disruption incident trail and finalised incident reports in a repo folder named:

agent_incidents/

(If the folder does not exist, create it.)

This logging must NOT meaningfully derail progress. Use the "two-phase logging" workflow below.

---

## Two-phase logging workflow (REQUIRED)

### Phase A — During the run: ultra-light timeline (bounded effort)
When an incident occurs, you MUST append a single concise entry to:

agent_incidents/timeline.md

This entry must take ~30–90 seconds to write. Do not write a full incident report mid-run.

**What counts as an incident (log it):**
1) A command fails (non-zero exit), OR produces an error/warning that changes your plan.
2) You realise you were operating in the wrong context (wrong directory, wrong worktree, wrong branch, wrong interpreter/venv).
3) You waste time due to an avoidable misunderstanding (path confusion, tool usage confusion, missing dependency, permissions).
4) You need more than one attempt to get a basic prerequisite working (install, build, test, lint, start service).
5) You notice a recurring "agent trap" even if caught quickly (e.g., "forgot to run poetry install" but fixed immediately).

**Timeline entry format (exactly this structure, one entry per incident):**
- `YYYY-MM-DD HH:MM TZ | <short title> | symptom: <what happened> | attempted: <what you tried> | status: OPEN|TENTATIVE|VERIFIED | verify: <command/check to prove it> | tags: [..]`

Rules:
- Keep output excerpts out of the timeline (put them in the final incident report if needed).
- If you don't yet know the fix, set `attempted:` to `TBD` and `status: OPEN`.
- If you tried something that might work but isn't proven, use `status: TENTATIVE`.
- Only use `status: VERIFIED` after you have actually run the verification command/check and it succeeded.

### Phase B — Just before completion: finalise incident reports (polished, verified)
Immediately before declaring the overall task "done", you MUST:
1) Read agent_incidents/timeline.md
2) Create or update one markdown incident file per timeline entry in:
   agent_incidents/incidents/
3) Ensure each incident has a clear resolution and a verification step.
4) Ensure statuses are correct:
   - VERIFIED only if a real verification succeeded
   - If something is still unverified but the main task can complete, keep it TENTATIVE and explain why

Also maintain an index file:
agent_incidents/README.md
Add a bullet link for each incident file.

---

## Hygiene and security (STRICT)
- Never write secrets (tokens, API keys, private URLs). Redact with `[REDACTED]`.
- Keep copied command output minimal (3–10 lines, only what matters).
- Prefer concrete facts over speculation. If uncertain, say so.

---

## File structure & naming

agent_incidents/
  README.md
  timeline.md
  incidents/
    INC-0001-<slug>.md
    INC-0002-<slug>.md
    ...

ID rules:
- Prefer sequential IDs by scanning existing INC-*.md and incrementing.
- If scanning is hard, use timestamp IDs: INC-YYYYMMDD-HHMM-<slug>.md

Slug rules:
- short, kebab-case, describes the root issue (e.g., `wrong-repo-root`, `poetry-install-fails`, `worktree-path-confusion`)

---

## Incident report template (use exactly this structure)

```markdown
---
id: INC-0001
status: OPEN | TENTATIVE | VERIFIED
timestamp_opened: YYYY-MM-DDTHH:MM:SS±TZ
timestamp_resolved: YYYY-MM-DDTHH:MM:SS±TZ  # omit if OPEN
task_context: "<one sentence summary of the objective you were pursuing>"
severity: LOW | MEDIUM | HIGH | BLOCKER
classification: dependency | pathing | repo_state | tooling | permissions | config | test_failure | runtime
tags: [paths, worktree, poetry, deps, permissions, tests, tooling, config]  # pick relevant
related_timeline_entries:
  - "<copy the exact timeline line(s) for this incident>"
---

# Summary (1–2 sentences)
What went wrong and the impact.

# Environment snapshot (minimal but useful)
- cwd:
- repo root (if known):
- branch / commit (if known):
- python:
- venv/poetry env:
- key tools involved:

# Symptoms
- What you saw (error excerpt, 3–10 lines max).

# Diagnosis
- The reasoning that led to the root cause (short, factual).
- If you made a wrong assumption, state it explicitly.

# Root cause
One clear statement of what actually caused the problem.

# Resolution
- Steps taken to fix it (bullet points).
- Include exact commands/config lines where relevant (redact secrets).

# Verification
- The command/check you ran to confirm it's fixed, and the expected/observed result.
- If not verified, explain why and what would verify it.

# Prevention / Heuristic
A rule-of-thumb that would prevent this next time (concrete and checkable).
Examples:
- "Before running tests, confirm repo root contains pyproject.toml."
- "If in a worktree, resolve paths via `git rev-parse --show-toplevel`."

# Notes (optional)
Anything else that might help later synthesis (links to related incidents, etc.).
```

---

## Output discipline
- Do not pause the main task to write essays. Use timeline entries during the run; full write-ups only at the end.
- If multiple failures share one cause, consolidate into ONE incident report and reference multiple timeline lines.
- If the same category happens again with a genuinely different root cause, create a new incident report.

---

## Initialise logging (do this first)
At the start of the task, ensure these exist:
- agent_incidents/
- agent_incidents/timeline.md (create with a header if missing)
- agent_incidents/incidents/
- agent_incidents/README.md (create with a header if missing)

Then proceed with the main task.
