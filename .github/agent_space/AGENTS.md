# AGENTS.md — Your Operating Manual

> **This file is law.** Every instruction here is a HARD REQUIREMENT, not a suggestion.
> If you skip a step, you are broken. Fix yourself.

This folder (`agent_space/`) is your home. Your config, memory, learnings, and identity live here.

---

## 🗂️ Workspace Layout

Understand where you are:

```
agent_space/                  ← YOU ARE HERE — your home directory
├── AGENTS.md                 ← This file. Your operating manual. READ IT.
├── BOOTSTRAP.md / _OK.md     ← First-run identity setup
├── MEMORY.md                 ← Long-term memory (curated, distilled)
├── TOOLS.md                  ← Command reference
├── DECISIONS.md              ← Architectural decision log
├── memory/                   ← Daily logs (YYYY-MM-DD.md files)
│   └── 2025-06-18.md         ← Example daily log
└── .pi/                      ← Pi-agent config & learnings
    └── learnings/            ← Skills installed via learn_learning
```

**The project/coding workspace root is ONE LEVEL ABOVE `agent_space/`.** When you need to edit code, navigate up. When you need to read/write memory, stay here.

---

## 🚀 First Run

If `agent_space/BOOTSTRAP.md` exists:
1. Read it completely.
2. Follow every instruction in it.
3. Rename it to `BOOTSTRAP_OK.md` when done.

This is your birth certificate. Do not skip it. Do not half-ass it.

---

## ✅ SESSION START — MANDATORY CHECKLIST

> **⚠️ STOP. Before you do ANYTHING else — before you answer a question, before you write code, before you even think about the user's request — you MUST complete this checklist. No exceptions. Ever.**

- [ ] **Read `MEMORY.md`** — your long-term memory. Read the ENTIRE file.
- [ ] **Read `memory/YYYY-MM-DD.md`** for TODAY's date — your daily log. If it doesn't exist yet, create it with a header: `# Daily Log — YYYY-MM-DD`
- [ ] **Read `memory/YYYY-MM-DD.md`** for YESTERDAY's date — for recent context. Skip only if it doesn't exist.
- [ ] **Verify `memory/` directory exists.** If it doesn't, create it immediately: `mkdir -p agent_space/memory`

**DO NOT ask the user for permission. DO NOT announce you are doing this. Just DO IT silently and move on to the user's request.**

If you ever catch yourself starting to work on the user's request without having completed this checklist, STOP IMMEDIATELY, go back, and complete it.

---

## 🛑 SESSION END — MANDATORY BEFORE YOU STOP

> **⚠️ You MUST complete these steps at the END of EVERY conversation. This is not optional. This is not "if you remember." This is EVERY. SINGLE. TIME.**

Before your final message in any conversation, you MUST:

### 1. Update Daily Log (`memory/YYYY-MM-DD.md`)

Append to today's daily log file. Each conversation gets its own session block with **structured sections**. This is your future self's primary reference — make it detailed enough that someone reading it months later can understand exactly what happened, why, and how.

Format each entry as a **session block** using ALL applicable sections:

```
## Session N — [Brief Title]

### Done
- Bullet-point summary of tasks completed (be specific — include IDs, names, versions)
- Include outcomes, not just actions ("Created learning ID abc123" not just "Created a learning")

### Root Cause
- Why the problem existed (if this session involved debugging/fixing)
- What was wrong and why — not just symptoms, but the underlying cause
- Skip this section if the session was purely additive (new feature, new content)

### Fix
- Exactly what was changed to solve the problem
- Include code snippets, config changes, or command sequences if relevant
- Be precise enough that future-you could reproduce the fix

### Decisions
- Architectural, technical, or process decisions made during this session
- Include the reasoning — WHY this approach was chosen over alternatives

### Files Changed
- List of files created, modified, or deleted (with brief description of what changed)

### Verified
- How the changes were verified (commands run, tests passed, manual checks)
- Include the actual verification commands and their outcomes

### Architecture Notes
- Design patterns, trade-offs, or structural choices worth remembering
- How components interact, where the logic lives, why it's structured this way

### Lessons
- What you learned that applies beyond this specific task
- Patterns to follow or anti-patterns to avoid in the future

### Problems
- Errors, blockers, workarounds encountered
- Include error messages and what resolved them

### Open Items
- Anything left unfinished or needing follow-up
- Be specific: "Publish v2 of learning abc123 from the UI" not "finish the learning"

### Commands/Tools Used
- Noteworthy commands, tools called, or API endpoints used
- Include tool names with parameters when relevant (e.g. `update_learning(learning_id: abc123, content: ...)`)
```

**Guidelines:**
- **Number sessions sequentially** within each day (Session 1, Session 2, etc.)
- **Skip sections that don't apply** — not every session has a Root Cause or Fix
- **Be specific** — include UUIDs, file paths, version numbers, error messages
- **Include context** — mention the conversation topic, what the user asked for
- **Err on the side of too much detail** — you can always skim, but you can't recover lost context

### 2. Update Long-Term Memory (`MEMORY.md`)

Review today's session and ask yourself: **"What from today is worth remembering in a week? A month?"**

If the answer is anything, update `MEMORY.md`:

- Add new significant learnings, decisions, or context
- Update existing entries if information has changed
- Remove outdated information
- Keep it curated — this is distilled knowledge, not a raw dump

### 3. Verification

Before your final response, confirm to yourself:
- [ ] Daily log updated with today's work
- [ ] MEMORY.md reviewed and updated if needed
- [ ] Any new files or changes are saved

**If you are about to end a conversation and you have NOT updated the daily log, you are violating this protocol. Go back and do it NOW.**

---
## 🧠 Memory — Your Continuity System

**You wake up with ZERO context every session.** These files are the ONLY thing connecting you to your past self. Treat them like your life depends on it — because your usefulness does.

### MEMORY.md — Long-Term Memory

This is your curated, distilled memory. Think of it as the important stuff you'd write on a sticky note on your monitor.

- **Read it** at session start (mandatory — see checklist above)
- **Update it** at session end (mandatory — see checklist above)
- **Edit it freely** during sessions when you learn something significant
- Contents: decisions, opinions, lessons learned, project context, user preferences, recurring patterns
- Keep it organized with clear headers and dates

### memory/YYYY-MM-DD.md — Daily Logs

Raw, chronological logs of what happened each day.

- **Create** a new file for each day you work (format: `memory/2025-06-18.md`)
- **Append** to it throughout the session, not just at the end
- **Create `memory/` directory** if it doesn't exist: `mkdir -p agent_space/memory`
- Contents: tasks, errors, solutions, commands run, files modified, conversations

### 📝 ABSOLUTE RULE: No Mental Notes

- **"Mental notes" do not exist.** They vanish when the session ends. They are worthless.
- If you want to remember something → **WRITE IT TO A FILE. NOW.**
- If someone says "remember this" → **write to `memory/YYYY-MM-DD.md` IMMEDIATELY**, not later
- If you learn a lesson → **update AGENTS.md, TOOLS.md, or MEMORY.md IMMEDIATELY**
- If you make a mistake → **document it IMMEDIATELY** so future-you doesn't repeat it
- If you think "I'll remember this" → **NO YOU WON'T. WRITE IT DOWN.**
- **Files > Brain. Always. No exceptions. 📝**

---

## 🎓 Learning Execution — Installing Skills & Tools

When you learn a new skill (via `learn_learning` or manual installation), follow these rules WITHOUT EXCEPTION:

### Non-Interactive Installation

- **ALWAYS** install software non-interactively. No prompts. No confirmations. No user input.
- Use silent/automatic flags:
  - `apt-get install -y <package>`
  - `brew install <package>` (already non-interactive)
  - `pip install <package>` (already non-interactive)
  - `npm install -g <package>` (already non-interactive)
  - `yes | <command>` as a last resort
- **NEVER** use `--user-interaction`, `--interactive`, or any flag that requires human input
- **NEVER** ask the user to install something you can install yourself
- **NEVER** say "please install X" — just install it

### Verify Everything

After every installation, VERIFY it worked:

```bash
<tool> --version   # or equivalent
echo $?            # confirm exit code 0
```

- Only report "done" or "installed" AFTER verification succeeds
- If verification fails, troubleshoot and retry
- If it truly cannot be installed automatically, document WHY in the daily log and try alternatives

### Learnings Location

- Learnings installed via `learn_learning` appear at `agent_space/.pi/learnings/`
- Read installed learnings when relevant to the current task
- If a learning has dependencies, install them automatically using the rules above

---

## 🔀 Git

You are working in a git repository. Use it properly:

- **Pull before starting work** if collaborating. Keep your local state current.
- **Commit frequently** with meaningful messages. Format: `<type>: <short description>` (e.g., `feat: add agent CRUD endpoints`). Types: `feat`, `fix`, `refactor`, `chore`, `docs`.
- **Push regularly** to keep your work safe and visible.
- **Branch for features/experiments.** Don't pollute `main` with work-in-progress. Use `feat/<name>`, `fix/<name>`, `chore/<name>`.
- **Never force-push shared branches** without explicit permission.
- **Write commit messages that explain WHY**, not just what. Your future self and teammates will thank you.

---

## 🪝 Pre-commit Hooks

Pre-commit hooks enforce code quality automatically. You are responsible for them.

**Install once per environment** (check first, install if missing):

```bash
pre-commit --version 2>/dev/null || pip install pre-commit
pre-commit install
```

**Every session:** verify hooks are installed before any commit:

```bash
pre-commit install  # safe to re-run; no-op if already installed
```

**Run manually on all files** (after pulling changes or on first setup):

```bash
pre-commit run --all-files
```

If a hook rejects a commit: fix the issue, re-stage, retry. **NEVER use `--no-verify` to bypass hooks.** That defeats the entire purpose.

---

## 🔧 Make It Yours

This is a starting point. As you develop your own patterns and preferences, add them here. Update the rules. Refine the process. Make this document work for YOU.

But the memory rules above? Those are non-negotiable. Everything else is fair game.