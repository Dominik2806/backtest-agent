# Agents and their guardrails

Two Claude Code subagents will turn an idea into a strategy spec and into a signal function: the `strategy-architect` and the
`signal-coder` (F-17, F-18). The engine, the data layer and the metrics stay deterministic code that no agent writes
([ADR 0002](adr/0002-deterministic-core-llm-never-writes-engine.md)), and a coded signal runs only after a person approved its
idea and its code ([coded-signals.md](coded-signals.md), [ADR 0018](adr/0018-coded-signals-and-approval-gate.md)). This document
is about what keeps the agents on their side of that gate. The decisions are in [ADR 0019](adr/0019-agents-and-their-guardrails.md).
The project is educational and not investment advice.

**Every claim below ends with the test that checks it, `(test: file::name)`, or says `(not tested)`.** A test reads this file and
fails if a named test does not exist or a claim has neither (`tests/test_agents_docs.py`). A passing test shows what the code does
on the tested inputs; it does not show that Claude Code behaves as its documentation says. Where a claim is about Claude Code
itself, it says so.

## Status

What exists in this pull request (Phase 10 part 4a): the deny and ask rules, the hook `restrict_writes.py` and its entry in
`.claude/settings.json`, and the git-ignored folder `strategies/drafts/`. What does not exist yet: the agent files in
`.claude/agents/`, the three example specs, the fake agents and the end-to-end test. They come with part 4b, and until then
nothing starts an agent: the hook has been run on calls that tests wrote, never on a call of a real agent.

## The two agents (planned, files not built yet)

- The **strategy-architect** reads an idea, asks (through the main conversation) what is missing about timing, sizing, costs,
  universe and period, and writes one draft spec `strategies/drafts/<name>.yaml` with its assumptions in a comment header. It never
  runs a backtest. (planned; not tested)
- The **signal-coder** reads the `coded` block of an approved or drafted spec and writes `strategies/signals/<id>.py` and
  `strategies/signals/<id>.cases.yaml`, then checks them with `bt signal check`. It never approves anything. (planned; not tested)

## The fences

Three layers, none of them a boundary. The person who reads the code before `bt approve --code --sha` is the defence that counts. (not tested)

### Deny and ask rules

- `.claude/settings.json` denies `bt approve` in the spellings of the table below, for the Bash tool and for the PowerShell tool, and
  holds no allow rule for it. (test: `tests/test_agent_deny_rules.py::test_every_covered_spelling_is_matched`,
  `tests/test_agent_deny_rules.py::test_no_allow_rule_names_the_approval`)
- Every rule is needed by a spelling that no other rule matches, except the four plain rules for `uv run bt`, `python -m
  backtest_agent`, `py -m backtest_agent` and `python3 -m backtest_agent`, which stay on purpose: the meaning of a leading `*` in a
  rule is not documented, so the plain forms do not rely on it. (test:
  `tests/test_agent_deny_rules.py::test_removing_any_one_rule_leaves_a_covered_spelling_unmatched`,
  `tests/test_agent_deny_rules.py::test_each_redundant_rule_exists_and_matches_its_own_spelling`)
- The same spellings are in the `ask` list for `bt signal check`, for both tools, so Claude Code asks before it runs one. (test:
  `tests/test_agent_deny_rules.py::test_every_covered_spelling_is_matched`)
- The rules do not match `bt run`, `bt validate` or the other verb. (test:
  `tests/test_agent_deny_rules.py::test_other_commands_are_not_matched`)
- Deny and ask rules also apply to Claude Code's own session, not only to the agents: the main session cannot run `bt approve`
  either, and it is asked before `bt signal check` in Bash and in PowerShell. You run `bt approve` in your own shell. (test:
  `tests/test_agent_deny_rules.py::test_a_tool_without_rules_is_not_covered`; that the rules apply to the main session is a claim
  of the Claude Code documentation, not tested)
- The table is made with a reference matcher in the test. **It is our reading of the documented rule syntax, not the matcher of
  Claude Code**; the test shows that the rules say what we mean, not that Claude Code blocks the call. (test:
  `tests/test_agent_deny_rules.py::test_pattern_matches_follows_the_documented_wildcards`)

| Command (Bash tool) | Denied by the rules |
|---|---|
| `bt approve spec.yaml --idea` | yes |
| `uv run bt approve spec.yaml --idea` | yes |
| `python -m backtest_agent approve spec.yaml --idea` | yes |
| `py -m backtest_agent approve spec.yaml --idea` | yes |
| `python3 -m backtest_agent approve spec.yaml --idea` | yes |
| `bt.exe approve spec.yaml --idea` | yes |
| `.venv/Scripts/bt approve spec.yaml --idea` | yes |
| `cd work && bt approve spec.yaml --idea` | yes |
| `FOO=1 bt approve spec.yaml --idea` | yes |
| `sh -c 'bt approve spec.yaml --idea'` | no |
| `bash -c "bt approve spec.yaml --idea"` | no |
| `bt  approve spec.yaml --idea` (two spaces) | no |
| `bt 'approve' spec.yaml --idea` | no |

- The rows marked `no` are known gaps of the rules, asserted by a test so that this document cannot claim more. The Claude Code
  documentation names a full path, `sh -c` and a quoted word as not caught. The hook below is what refuses them for the two agents.
  (test: `tests/test_agent_deny_rules.py::test_the_known_gaps_are_not_matched`)

### The hook

- `.claude/hooks/restrict_writes.py` is a PreToolUse hook for the two agents. It is standard library only and imports nothing from
  `backtest_agent`; its id rules are compared with the project's own. (test:
  `tests/test_restrict_writes.py::test_the_id_rules_of_the_hook_are_the_rules_of_the_spec`)
- It exits 0 without printing anything, or exits 2 with the reason on stderr. **It never prints a `permissionDecision`**, so it
  cannot turn an ask rule into an allow. (test: `tests/test_restrict_writes_protocol.py::test_the_script_never_prints_a_decision`)
- A call without `agent_type` (the main session), or of another agent, gets no decision: exit 0, nothing printed. (test:
  `tests/test_restrict_writes_protocol.py::test_a_call_without_agent_type_is_the_main_session_and_gets_no_decision`,
  `tests/test_restrict_writes_protocol.py::test_a_call_of_another_agent_gets_no_decision`)
- Fail closed inside the script: input that is not a JSON object, an error in the decision and an unreadable stream are exit 2.
  (test: `tests/test_restrict_writes_protocol.py::test_stdin_that_is_not_a_json_object_is_blocked`,
  `tests/test_restrict_writes_protocol.py::test_an_error_inside_the_decision_is_blocked_not_passed`)
- A script that cannot run at all (a syntax error, a missing interpreter) exits 1 or 127, and Claude Code lets a call through for
  every exit code except 2 unless the entry says `"onFailure": "block"`. That is why the entry has it. (test:
  `tests/test_restrict_writes_protocol.py::test_a_script_that_cannot_run_exits_1_and_that_is_why_the_entry_needs_on_failure_block`;
  what Claude Code does with the key is a claim of its documentation, not tested)
- The script also accepts an agent name as its argument: that is the planned copy of the entry in the frontmatter of each agent. The
  agent files do not exist yet, so no real agent calls it that way and no test ties a file to its command line. (test:
  `tests/test_restrict_writes_commandline.py::test_the_frontmatter_line_blocks_a_forbidden_call_without_an_agent_type`)

### What each agent may do

- **strategy-architect.** Write, Edit and MultiEdit only `strategies/drafts/<name>.yaml`, with `<name>` of lowercase letters,
  digits, `-` and `_` (at most 64 characters, not a Windows device name). Bash only `bt validate strategies/drafts/<name>.yaml`,
  also as `uv run bt ...`. Nothing else, `bt signal check` and `bt validate --data` included. (test:
  `tests/test_restrict_writes.py::test_the_architect_may_write_a_draft`,
  `tests/test_restrict_writes.py::test_the_architect_may_write_nothing_else`,
  `tests/test_restrict_writes.py::test_the_architect_may_validate_a_draft`,
  `tests/test_restrict_writes.py::test_the_architect_may_not_check_a_signal_or_read_the_examples`)
- **signal-coder.** Write, Edit and MultiEdit only `strategies/signals/<id>.py` and `strategies/signals/<id>.cases.yaml`, with an
  `<id>` that passes the id rules of a coded signal. Bash only `bt validate SPEC` and `bt signal check SPEC [--strategies-dir
  strategies/signals]`, with `SPEC` in `strategies/drafts/` or `strategies/examples/`, also as `uv run bt ...`. (test:
  `tests/test_restrict_writes.py::test_the_coder_may_write_its_two_files_by_relative_and_absolute_path`,
  `tests/test_restrict_writes.py::test_the_coder_may_not_write_anywhere_else`,
  `tests/test_restrict_writes.py::test_the_coder_may_validate_and_check`,
  `tests/test_restrict_writes.py::test_the_signal_check_of_the_coder_has_one_form`)
- Neither agent writes in the other's folder, in `approvals/`, `src/`, `tests/`, `docs/`, `.claude/` or anywhere else, and every other
  command is refused. (test: `tests/test_restrict_writes.py::test_the_two_agents_do_not_share_a_folder`,
  `tests/test_restrict_writes.py::test_every_other_command_is_refused`)
- Paths are refused for `..`, an absolute path outside the folder, a link or junction out of it, UNC and device paths, an NTFS
  stream, a component that ends in a dot or a space, a name that has to be lowercase, and a folder in the wrong case where the
  system tells case apart. (test: `tests/test_restrict_writes.py::test_a_path_with_dot_dot_is_refused_even_when_it_lands_in_the_folder`,
  `tests/test_restrict_writes.py::test_an_absolute_path_outside_the_project_is_refused`,
  `tests/test_restrict_writes.py::test_a_junction_or_link_from_the_folder_to_somewhere_else_is_refused`,
  `tests/test_restrict_writes.py::test_unc_and_device_paths_are_refused`,
  `tests/test_restrict_writes.py::test_an_ntfs_stream_is_refused`,
  `tests/test_restrict_writes.py::test_a_trailing_dot_or_space_is_refused`,
  `tests/test_restrict_writes.py::test_a_wrong_case_in_the_folder_is_the_same_folder_only_where_the_system_says_so`)
- A Bash command passes only if every character is a letter, a digit, `_`, `.`, `/`, `-` or a single space between words. A
  backslash is refused with its own reason, so paths are written with forward slashes. Quotes, globs, `$`, backticks, `;`, `&`, `|`,
  `<`, `>`, newlines and tabs, environment prefixes and `cd x &&` are refused. The agents use the Bash tool (Git Bash on Windows);
  every PowerShell call by them is refused. (test: `tests/test_restrict_writes.py::test_a_backslash_is_refused_with_its_own_reason`,
  `tests/test_restrict_writes.py::test_a_shell_character_gets_the_allowlist_reason`,
  `tests/test_restrict_writes.py::test_every_other_tool_is_refused`)

### Drafts and public files

- `strategies/drafts/` is git-ignored except an empty `.gitkeep`, so a draft stays private until a person moves a spec on. (test:
  `tests/test_agent_drafts_ignored.py::test_git_ignores_a_draft`,
  `tests/test_agent_drafts_ignored.py::test_git_does_not_ignore_anything_else`)
- `strategies/signals/` and `approvals/` are tracked, so public. **`git add` a signal file only after you have read the code.** An
  agent must not add, commit or push; the hook does not allow `git` at all. (test:
  `tests/test_restrict_writes.py::test_every_other_command_is_refused`)

## May an agent run `bt signal check`?

- **The strategy-architect may not; the signal-coder may.** (test:
  `tests/test_restrict_writes.py::test_the_architect_may_not_check_a_signal_or_read_the_examples`,
  `tests/test_restrict_writes.py::test_the_coder_may_validate_and_check`)
- **Not unattended.** An agent that runs the command runs its own code with its own permissions, as it could with Python; the only
  limit of an agent run is the timeout of its own tool. The subprocess hardening, a wall-clock limit and a memory limit, is NOT
  built ([ADR 0018](adr/0018-coded-signals-and-approval-gate.md), addendum, known gap 6). (test:
  `tests/test_agents_docs.py::test_the_binding_sentences_of_the_adr_are_kept`)
- What stands between the coder and a run that nobody sees is the ask rule of `.claude/settings.json` and nothing else: the hook
  looks at no permission mode (see "Details of the hook"). Whether Claude Code shows the prompt in the `auto` mode, with
  `dontAsk`, under `bypassPermissions` or in a background agent has not been tested. (not tested)
- **Do not run these agents with `bypassPermissions`.** Whether PreToolUse hooks run under `bypassPermissions` was not tested, and the
  documentation does not say. (not tested)

## How the hook is called

The entry is in `.claude/settings.json`, where hooks also run with `claude -p` and in a folder that was never trusted (a claim of
the Claude Code documentation, not tested). It is this one line, in the shell form, which Claude Code runs with Git Bash on
Windows:

```text
input=$(cat; echo x); input=${input%x}; case "$input" in *agent_type*) printf '%s' "$input" | uv run --no-project python -I "$CLAUDE_PROJECT_DIR/.claude/hooks/restrict_writes.py" ;; esac
```

- The block above is the line of `.claude/settings.json`, character for character. (test:
  `tests/test_agents_docs.py::test_the_hook_line_in_this_document_is_the_line_of_settings_json`)
- The shell reads all of stdin, keeps its trailing newlines, and starts `uv` only if the bare text `agent_type` occurs in it. So a
  main-session call never starts `uv`, and a broken `uv` or interpreter cannot block it. A call whose content merely contains the
  text starts the script, which finds no `agent_type` key and says nothing. (test:
  `tests/test_restrict_writes_commandline.py::test_the_shortcut_table`,
  `tests/test_restrict_writes_commandline.py::test_the_settings_line_does_not_start_the_hook_for_the_main_session`)
- The input reaches the script byte for byte. (test: `tests/test_restrict_writes_commandline.py::test_the_input_reaches_the_script_unchanged`)
- It works from the project root and from another directory, because the path is built from `$CLAUDE_PROJECT_DIR`. (test:
  `tests/test_restrict_writes_commandline.py::test_the_settings_line_blocks_a_forbidden_call_of_an_agent`,
  `tests/test_restrict_writes_commandline.py::test_the_settings_line_has_no_objection_to_an_allowed_call`; that Claude Code sets and
  expands the variable is a claim of its documentation, not tested)
- **Why `uv run --no-project python -I`.** On the development machine `uv.exe` is a real executable and runs the Python 3.12 of the
  project, while `python` is a 3.13 next to a Windows Store stub. `-I` ignores `PYTHONPATH` and the script directory;
  `--no-project` avoids a sync. The documentation does not recommend one of `python`, `py` and `uv run python`. (not tested)
- The entry has `"onFailure": "block"` and a timeout of at most 60 seconds (the file has 30). (test:
  `tests/test_restrict_writes_commandline.py::test_the_settings_entry_has_the_shape_the_design_needs`)
- With no `uv` on the path an agent call fails with exit 127 (which only `onFailure` turns into a block) and a main-session call still
  exits 0. (test: `tests/test_restrict_writes_commandline.py::test_a_broken_environment_blocks_only_where_the_hook_is_needed`)
- Cost, measured once on one machine (Windows 11, 15 runs each, medians): about 50 ms for a main-session call, 94 to 141 ms for one
  start of the script, 156 ms (parallel) to 237 ms (one after the other) for two starts. (not tested)

## When the hook breaks

- **`uv` or the interpreter is missing, or the script has an error.** Calls of the two agents are blocked (`onFailure`), the main
  session is not touched. Fix `uv`, or remove the entry: delete the `"hooks"` key of `.claude/settings.json`. The deny and ask rules
  stay. Without the entry the agents are limited by the rules and by their frontmatter copy only (when it exists and the folder is
  trusted). (test: `tests/test_restrict_writes_commandline.py::test_a_broken_environment_blocks_only_where_the_hook_is_needed`)
- **The hook blocks something it should allow.** Read the reason on stderr (`restrict_writes: blocked: ...`). The table of "What
  each agent may do" says what is allowed; change the hook and its table test together. (test:
  `tests/test_restrict_writes_protocol.py::test_the_script_exits_2_with_the_reason_on_stderr_when_it_blocks`)
- **`.claude/settings.json` is strict JSON.** A comment or a trailing comma makes Claude Code report a Settings Error for the file,
  and then the deny rules may be lost with it; open `/permissions` after every edit to see that they are listed, and run `claude
  doctor`. (not tested)

## What the Claude Code documentation says and we did not test

- **`onFailure` needs Claude Code 2.1.295 or later.** The key is in the Claude Code documentation (hooks, "Hook handler fields") but
  not in the SchemaStore schema of `settings.json`, whose command-hook definition allows no other keys, so an editor that validates
  against the schema may warn. The documentation does not say what an older version does with the key; if it treats an unknown key as
  an error, the whole file may be skipped and the deny rules with it. (not tested)
- Only exit code 2 blocks a call; any other exit code is a non-blocking error unless `onFailure` is `"block"`. (not tested; the exit
  code 1 of a broken script is tested)
- Hooks of `settings.json` run with `claude -p` and in an untrusted folder; hooks in the frontmatter of a project agent are skipped
  until the folder is trusted. The hook needs a working interpreter and, for the frontmatter copy, the workspace trust. (not tested)
- Deny rules hold in every permission mode. Ask rules, and hooks, under `bypassPermissions`: not documented, not tested. (not tested)

## Details of the hook

These four paragraphs are separate on purpose: each states one detail that may change, with its test. (not tested)

The tools the hook sees. The entry matches Write, Edit, MultiEdit, NotebookEdit, Bash and PowerShell. For the two agents the hook
decides on the first three by path and on Bash by command, and refuses NotebookEdit, PowerShell and any other tool name it is given.
Read, Glob and Grep are not matched, so the hook never sees them. (test:
`tests/test_restrict_writes_commandline.py::test_the_settings_entry_has_the_shape_the_design_needs`,
`tests/test_restrict_writes.py::test_every_other_tool_is_refused`)

The permission mode. The hook reads no permission mode: the same call gets the same decision in every mode. (test:
`tests/test_restrict_writes_protocol.py::test_the_decision_does_not_depend_on_a_permission_mode`)

The 8.3 rule. A path component with `~` followed by a digit, such as `RSIPUL~1.py`, is refused, also when the rest of the name would
be allowed. (test: `tests/test_restrict_writes.py::test_an_8_3_short_name_is_refused`)

Stdin decoding. The script reads its input as UTF-8. No test covers that line: with it removed, every test still passes on the
development machine, where stdin is cp1252. (not tested)

## Known gaps

- The deny and ask rules are text rules. A spelling that is not in the table above is not denied. (test:
  `tests/test_agent_deny_rules.py::test_the_known_gaps_are_not_matched`)
- The hook is a fence: a person who can write to `.claude/` can remove it, and an agent that gets a tool the hook does not know
  would be refused only by this hook. Whether `Bash` in an agent's `tools` also grants PowerShell, and whether MCP tools are
  inherited, is not documented. (not tested)
- The settings entry decides by `agent_type`. If Claude Code sends another value for an agent than its file name, the settings entry
  gives no decision for it and only the frontmatter copy, in a trusted folder, holds. (not tested)
- The static check is a tripwire, not a sandbox, and `bt signal check` runs unapproved code (known gaps of
  [ADR 0018](adr/0018-coded-signals-and-approval-gate.md)). (not tested)

## Tests

The tests of this document are `tests/test_agent_deny_rules.py`, `tests/test_restrict_writes.py`,
`tests/test_restrict_writes_protocol.py`, `tests/test_restrict_writes_commandline.py`, `tests/test_agent_drafts_ignored.py` and
`tests/test_agents_docs.py`. The mutation tables of the pull request are in its report, not in the repository.
