# Contributing

Thanks for your interest in `backtest-agent`. The project is built in phases described in
[docs/ROADMAP.md](docs/ROADMAP.md); that file is the source of truth for scope and process.

## Setup

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 and the virtual environment) and Git.
The maintainer works on Windows with PowerShell; the commands also work in other shells.

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Workflow

- `main` is protected. No direct pushes; changes arrive via pull request and CI must be green.
- One short-lived branch per phase or change, created from `main`.
- PRs are squash-merged, and the branch is deleted afterwards.
- Keep PRs small. Two manageable pull requests are better than one huge one.

### Branch names

| Prefix | Used for | Example |
|---|---|---|
| `feature/` | New functionality | `feature/core-engine` |
| `fix/` | Bug fix | `fix/benchmark-dates` |
| `docs/` | Documentation only | `docs/roadmap` |
| `chore/` | Setup, CI, dependencies, releases | `chore/repo-setup` |

### Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/): `feat`, `fix`, `docs`, `test`, `chore`.
Example: `feat(engine): add vectorized portfolio engine (F-09)`.

The pull request title follows the same format, because it becomes the squash commit. Commit messages and pull
request descriptions contain only the message or a plain description, without attribution trailers.

## Branch protection

`main` is protected in the GitHub repository settings (a branch protection rule or ruleset for `main`):

- require a pull request before merging, so there are no direct pushes;
- require status checks to pass before merging: `check (ubuntu-latest)` and `check (windows-latest)`, the two jobs
  of the CI workflow (`.github/workflows/ci.yml`). Renaming the job or changing the matrix means updating the rule;
- allow squash merging only, and delete the branch after the merge.

Only the repository owner can change these settings.

## Definition of Done

- **Works:** acceptance criteria are met and checked by hand.
- **Tested:** new logic has tests; CI is green.
- **Clean:** the linter reports nothing; no secrets and no generated files in the commit.
- **Documented:** README or `docs/` are updated and the CHANGELOG has an entry under "Unreleased".
- **CLAUDE.md current:** new commands and conventions are recorded.

## Releasing

See [docs/RELEASING.md](docs/RELEASING.md).

## Language

Code, commits, documentation and the README are written in English.
