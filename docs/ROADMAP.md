# Roadmap

This document is the source of truth for how `{{project-name}}` is built. Every phase is one branch and one pull
request. Claude Code reads this file at the start of each phase.

## Project overview

**{{Project name}}** is {{one-paragraph description}}.

### Building blocks

{{List or table of the main parts of the project.}}

### Tech stack

{{Language, tools, services.}}

## Architecture

{{Short summary or diagram; details live in [architecture.md](architecture.md).}}

## Git workflow

- **`main` is protected.** No direct pushes. Changes arrive via pull request, CI must be green.
- **One branch per phase**, short-lived, created from `main`.
- **Squash merge.** Every PR becomes one clean commit on `main`; the branch is deleted afterwards.
- **Small PRs.** Two manageable pull requests are better than one huge one.

| Prefix | Used for | Example |
|---|---|---|
| `feature/` | New functionality | `feature/{{short-description}}` |
| `fix/` | Bug fix | `fix/{{short-description}}` |
| `docs/` | Documentation only | `docs/{{short-description}}` |
| `chore/` | Setup, CI, dependencies | `chore/{{short-description}}` |

**Commits** follow [Conventional Commits](https://www.conventionalcommits.org/): `feat`, `fix`, `docs`, `test`, `chore`
(for example `feat({{scope}}): {{what changed}}`).

**Versions** follow [Semantic Versioning](https://semver.org/) and are published as a Git tag with a GitHub release,
see [RELEASING.md](RELEASING.md): `v0.1.0` after {{first milestone}}, `v1.0.0` after {{stable milestone}}.

**Language:** {{code, commits, documentation and the README language}}.

### Routine for each phase

1. Create the branch: `git switch main; git pull; git switch -c <branch>`
2. Explore and plan: start Claude Code in Plan Mode, review the plan before any code is written.
3. Code: implement the plan, review intermediate steps, steer when needed.
4. Verify: {{test and lint commands}}, tick off the acceptance criteria.
5. Commit and open a PR: conventional commit, PR description, CHANGELOG entry under "Unreleased".
6. Merge: CI green, squash merge, delete the branch, update local `main`.

### Definition of Done

- **Works:** all acceptance criteria of the phase are met and checked by hand.
- **Tested:** new logic has tests; CI is green.
- **Clean:** the linter reports nothing; no secrets and no generated files in the commit.
- **Documented:** README or `docs/` are updated, the CHANGELOG has an entry.
- **CLAUDE.md current:** new commands and conventions are in the project memory.
- **Merged:** pull request squash-merged into `main`, branch deleted.

## Phases at a glance

| Phase | Branch | Result | Effort | Status |
|---|---|---|---|---|
| 0 | `chore/repo-setup` | Project skeleton, CI, CLAUDE.md, templates | {{estimate}} | {{Planned}} |
| 1 | `feature/{{name}}` | {{result}} | {{estimate}} | {{Planned}} |

### Deviations from the plan

- {{Record every deviation from the plan here, with the reason and the PR number.}}

---

## Phase 0: Repo setup

**Branch:** `chore/repo-setup` · **Goal:** a clean public repository in which every later phase only adds content.

Tasks:

- Project skeleton and folder structure as in the architecture.
- Quality: linter, tests, and a GitHub Actions workflow that runs on every pull request.
- Docs foundation: README skeleton, `CONTRIBUTING.md`, `CHANGELOG.md`, PR and issue templates.
- `CLAUDE.md`: project goal, commands and conventions.

Done when:

- A test PR triggers CI and it runs green.
- {{install-command}} and {{test-command}} work on a fresh clone.
- README, `CLAUDE.md` and `docs/ROADMAP.md` describe the goal and the process of the project.

## Phase 1: {{Name}}

**Branch:** `feature/{{name}}` · **Goal:** {{one sentence}}.

Tasks:

- {{task}}

Done when:

- {{acceptance criterion that can be checked}}

## Outlook

- {{Ideas that are not planned yet.}}
