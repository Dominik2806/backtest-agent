# CLAUDE.md

## Project goal

{{What the project is and its core principle, in two or three sentences.}}

**Read `docs/ROADMAP.md` at the start of each phase.** It is the source of truth for scope, architecture,
git workflow and the Definition of Done. Work on one phase at a time.

## Tech stack

{{Language and version, package manager, frameworks, test and lint tools, CI.}}

## Commands

```bash
{{install-command}}      # install dependencies
{{test-command}}         # run tests
{{lint-command}}         # lint
{{format-command}}       # format (CI runs the check variant)
```

## Workflow

{{How Claude should work on this project: procedures, rules it must always follow, what it must never do
automatically, and what to do when a guardrail blocks something.}}

## Conventions

- **Language:** {{code, commits, docs and README language}}.
- **Layout:** {{where source, tests, docs and generated files live.}}
- **Docs:** every relative markdown link in `README.md` and `docs/**/*.md` must resolve. Decisions go into
  `docs/adr/` (one short ADR per decision, listed in its `README.md`).
- **Branches:** one per phase or change, created from `main`, named `feature/`, `fix/`, `docs/` or `chore/` plus a
  short kebab-case description. Never push directly to `main`.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) with types `feat`, `fix`, `docs`,
  `test`, `chore` (e.g. `feat({{scope}}): {{what changed}}`).
- **PRs:** squash-merged; add a CHANGELOG entry under "Unreleased".
- **Releases:** follow `docs/RELEASING.md`.
- **Never commit** secrets, `.env` or {{generated files}}.
- Update this file when new commands or conventions are introduced.
