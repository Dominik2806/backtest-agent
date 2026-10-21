# {{project-name}}

[![CI](https://github.com/{{owner}}/{{repo}}/actions/workflows/ci.yml/badge.svg)](https://github.com/{{owner}}/{{repo}}/actions/workflows/ci.yml)
[![License: {{license}}](https://img.shields.io/badge/license-{{license}}-blue.svg)](LICENSE)
[![{{language}} {{language-version}}](https://img.shields.io/badge/{{language}}-{{language-version}}-blue.svg)]({{version-file}})

{{one-paragraph pitch: what the project is, who it is for, and its core principle.}}

## What it does

{{Two or three short paragraphs: the typical use, with a concrete example, and what the user gets out of it.}}

## Requirements

- {{tool-1}} ({{why it is needed}})
- {{tool-2}}

## Quickstart

```bash
git clone https://github.com/{{owner}}/{{repo}}.git && cd {{repo}}
{{command-1}}
{{command-2}}
```

{{What the user sees or should do next, and the expected result. The quickstart must work on a fresh clone.}}

## What is inside

| Part | What it does | Where |
|---|---|---|
| {{part-1}} | {{description}} | [`{{path}}`]({{path}}), [docs](docs/{{doc}}.md) |
| {{part-2}} | {{description}} | [`{{path}}`]({{path}}) |

How the parts fit together: [docs/architecture.md](docs/architecture.md). Why they are built this way:
[docs/adr/](docs/adr/README.md).

## {{Domain section, e.g. Usage or Examples}}

{{Delete this section if the project has no use for it, or rename it.}}

## Safety

{{Guardrails, limits and trust boundaries a user should know about. Delete if not applicable.}}

## Development

```bash
{{install-command}}
{{test-command}}
{{lint-command}}
{{format-check-command}}
```

`main` is protected: one branch per change (`feature/`, `fix/`, `docs/`, `chore/`), Conventional Commits, squash-merged
pull requests with a CHANGELOG entry. See [CONTRIBUTING.md](CONTRIBUTING.md). Further reading:
[roadmap](docs/ROADMAP.md), [changelog](CHANGELOG.md), [releasing](docs/RELEASING.md).

## Roadmap status

| Phase | Result | Status |
|---|---|---|
| 0 | Project skeleton, CI, templates | {{Done / In progress / Planned}} |
| 1 | {{result}} | {{status}} |

Outlook (not started): {{short list of ideas beyond the current roadmap.}}

## License

[{{license}}](LICENSE)
