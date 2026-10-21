# Contributing

Thanks for your interest in `{{project-name}}`. The project is built in phases described in
[docs/ROADMAP.md](docs/ROADMAP.md); that file is the source of truth for scope and process.

## Setup

Requires {{tool-requirements}}.

```bash
{{install-command}}
{{test-command}}
{{lint-command}}
{{format-check-command}}
```

## Workflow

- `main` is protected. No direct pushes; changes arrive via pull request and CI must be green.
- One short-lived branch per phase or change, created from `main`.
- PRs are squash-merged, and the branch is deleted afterwards.
- Keep PRs small. Two manageable pull requests are better than one huge one.

### Branch names

| Prefix | Used for | Example |
|---|---|---|
| `feature/` | New functionality | `feature/{{short-description}}` |
| `fix/` | Bug fix | `fix/{{short-description}}` |
| `docs/` | Documentation only | `docs/{{short-description}}` |
| `chore/` | Setup, CI, dependencies, releases | `chore/{{short-description}}` |

### Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/): `feat`, `fix`, `docs`, `test`, `chore`.
Example: `feat({{scope}}): {{what changed}}`.

The pull request title follows the same format, because it becomes the squash commit.

## Definition of Done

- **Works:** acceptance criteria are met and checked by hand.
- **Tested:** new logic has tests; CI is green.
- **Clean:** the linter reports nothing; no secrets and no generated files in the commit.
- **Documented:** README or `docs/` are updated and the CHANGELOG has an entry under "Unreleased".
- **CLAUDE.md current:** new commands and conventions are recorded.

## Releasing

See [docs/RELEASING.md](docs/RELEASING.md).

## Language

Code, commits, documentation and the README are written in {{language, e.g. English}}.
