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

What exists: from Phase 10 part 4a the deny and ask rules, the hook `restrict_writes.py` with its entry in `.claude/settings.json`,
and the git-ignored folder `strategies/drafts/`; from part 4b so far the two agent files `.claude/agents/strategy-architect.md` and
`.claude/agents/signal-coder.md`. What does not exist yet: the three example specs, the fake agents and the end-to-end test; they
come in the next commits of part 4b. The tests of this repository run the hook on calls that they write; the hook was seen on calls
of real agents once (see "Observations").

## The two agents

- The **strategy-architect** (`.claude/agents/strategy-architect.md`) turns an idea into one draft spec
  `strategies/drafts/<name>.yaml` and checks it with `bt validate`. Its prompt names `uv run bt validate` as the only command to run and
  `uv run bt approve ... --idea` as a command for the person only, and has it return its open questions in its final message, because a
  subagent cannot ask the person (a claim of the Claude Code documentation, not tested). (test:
  `tests/test_agent_files.py::test_prompts_name_only_commands_the_hook_allows`,
  `tests/test_agent_files.py::test_person_commands_are_refused_for_the_agent_and_parse`)
- The **signal-coder** (`.claude/agents/signal-coder.md`) writes `strategies/signals/<id>.py` and `strategies/signals/<id>.cases.yaml`
  and checks them with `bt validate` and `bt signal check`. Its prompt names `uv run bt approve` only as a command for the person, tells it
  to finish when `bt signal check` is refused and to say so in its final message, and tells it not to try another way round a
  refusal and not to advise switching the permission mode. (test: `tests/test_agent_files.py::test_coder_prompt_has_sentence_a`,
  `tests/test_agent_files.py::test_both_prompts_have_sentence_b`, `tests/test_agent_files.py::test_prompts_give_no_mode_advice`)
- The prompts spell the commands `uv run bt ...`, the spelling that works without an activated virtual environment (in the one real
  run `bt` alone was not on the PATH of the agent, see "Observations"). The hook allows both spellings. (test:
  `tests/test_agent_files.py::test_prompts_name_only_commands_the_hook_allows`)
- What a real run of either agent does is not tested: it was observed once (see "Observations"). (not tested)

## The fences

Two fences, the rules and the hook, and the person who reads the code. Neither fence is a boundary: the person who reads the code
before `bt approve --code --sha` is the defence that counts. (not tested)

### Deny and ask rules

- `.claude/settings.json` denies `bt approve` in the spellings of the table below, for the Bash tool and for the PowerShell tool, and
  holds no allow rule for it. (test: `tests/test_agent_deny_rules.py::test_every_covered_spelling_is_matched`,
  `tests/test_agent_deny_rules.py::test_no_allow_rule_names_the_approval`)
- Every rule is the only one to match some spelling, except the four plain rules for `uv run bt`, `python -m backtest_agent`,
  `py -m backtest_agent` and `python3 -m backtest_agent`, which stay on purpose: the meaning of a leading `*` in a rule is not
  documented, so the plain forms do not rely on it. A rule that is removed fails the first test, an extra or redundant rule the
  second, and a removed plain rule the third. (test:
  `tests/test_agent_deny_rules.py::test_every_covered_spelling_is_matched`,
  `tests/test_agent_deny_rules.py::test_removing_any_one_rule_leaves_a_covered_spelling_unmatched`,
  `tests/test_agent_deny_rules.py::test_each_redundant_rule_exists_and_matches_its_own_spelling`)
- The same spellings are in the `ask` list for `bt signal check`, for both tools, so Claude Code asks before it runs one. (test:
  `tests/test_agent_deny_rules.py::test_every_covered_spelling_is_matched`)
- The rules do not match `bt run`, `bt validate` or the other verb. (test:
  `tests/test_agent_deny_rules.py::test_other_commands_are_not_matched`)
- Deny and ask rules also apply to Claude Code's own session, not only to the agents: the main session cannot run `bt approve`
  either, and it is asked before `bt signal check` in Bash and in PowerShell. You run `bt approve` in your own shell. (not tested)
- `bt` has no global option before its command (only `--help` and `--version`, which exit), so a spelling such as `bt --flag
  approve` does not exist. (test: `tests/test_agent_deny_rules.py::test_bt_has_no_global_options_so_no_flag_can_stand_between_bt_and_the_command`)
- The table is made with a reference matcher in the test. **It is our reading of the documented rule syntax, not the matcher of
  Claude Code**; the test shows that the rules say what we mean, not that Claude Code blocks the call. (test:
  `tests/test_agent_deny_rules.py::test_pattern_matches_follows_the_documented_wildcards`)

| Command (Bash tool) | Matched by the rules (our reading of the syntax) |
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
| `$(bt approve spec.yaml --idea)` | no |
| `(bt approve spec.yaml --idea)` | no |
| `eval "bt approve spec.yaml --idea"` | no |
| `BT approve spec.yaml --idea` | no |

- The rows marked `no` are examples of what the rules do not match, asserted by a test so that this document cannot claim more; the
  list is `GAPS`, `GAPS_BASH` and `GAPS_POWERSHELL` in `tests/test_agent_deny_rules.py`. It also holds a backtick substitution and,
  for PowerShell, a path with backslashes such as `.\.venv\Scripts\bt.exe approve spec.yaml`. The Claude Code documentation names a
  full path, `sh -c` and a quoted word as not caught, and says that it also checks command substitutions, which our matcher does
  not (that Claude Code's documentation says so is not tested). The hook below is what refuses all of them for the two agents. (test:
  `tests/test_agent_deny_rules.py::test_the_known_gaps_are_not_matched`)

### The hook

- `.claude/hooks/restrict_writes.py` is a PreToolUse hook for the two agents. It imports only the standard library and nothing from
  `backtest_agent`, and its id rules are compared with the project's own. (test:
  `tests/test_agents_docs.py::test_the_hook_imports_only_the_standard_library`,
  `tests/test_restrict_writes.py::test_the_id_rules_of_the_hook_are_the_rules_of_the_spec`)
- It exits 0 without printing anything, or exits 2 with the reason on stderr. **It never prints a `permissionDecision`**, so it
  cannot turn an ask rule into an allow. (test: `tests/test_restrict_writes_protocol.py::test_the_script_never_prints_a_decision`)
- An exit 0 is no decision: Claude Code goes on with its normal permission flow, so the permission mode still decides whether a
  write of an agent asks for a prompt. A write that the hook allows is not thereby approved. (test:
  `tests/test_restrict_writes_protocol.py::test_the_script_never_prints_a_decision`; what Claude Code does with it is a claim of its
  documentation, not tested)
- A call without `agent_type` (the main session), or of another agent, gets no decision: exit 0, nothing printed. (test:
  `tests/test_restrict_writes_protocol.py::test_a_call_without_agent_type_is_the_main_session_and_gets_no_decision`,
  `tests/test_restrict_writes_protocol.py::test_a_call_of_another_agent_gets_no_decision`)
- Fail closed inside the script: input that is not a JSON object, an error in the decision and an unreadable stream are exit 2.
  (test: `tests/test_restrict_writes_protocol.py::test_stdin_that_is_not_a_json_object_is_blocked`,
  `tests/test_restrict_writes_protocol.py::test_an_error_inside_the_decision_is_blocked_not_passed`)
- A script that cannot run at all (a syntax error, a missing interpreter) exits 1 or 127, and Claude Code lets a call through for
  every exit code except 2 unless the entry says `"onFailure": "block"`. That is why the entry has it. (test:
  `tests/test_restrict_writes_protocol.py::test_a_script_that_cannot_run_exits_1_and_that_is_why_the_entry_needs_on_failure_block`,
  `tests/test_restrict_writes_commandline.py::test_a_broken_environment_blocks_only_where_the_hook_is_needed`; what Claude Code does
  with the key is a claim of its documentation, see "Observations")
- The script also accepts an agent name as its argument: that is the copy of the entry in the frontmatter of each agent file (see
  "The agent files"). (test:
  `tests/test_restrict_writes_commandline.py::test_the_frontmatter_line_blocks_a_forbidden_call_without_an_agent_type`)

### The agent files

- `.claude/agents/` holds exactly the two files; a third file would be an agent without the fence. (test:
  `tests/test_agent_files.py::test_agents_folder_has_exactly_the_two_files`)
- Each file lists the tools `Read, Glob, Grep, Write, Edit, Bash` and no other, and has only the keys `name`, `description`, `tools`
  and `hooks`: no `permissionMode`, `mcpServers` or `disallowedTools`. (test:
  `tests/test_agent_files.py::test_tools_are_exactly_read_glob_grep_write_edit_bash`,
  `tests/test_agent_files.py::test_frontmatter_keys_are_name_description_tools_hooks`)
- Each file carries a copy of the hook entry with no matcher and no `if`, the handler of `settings.json` (type, shell, onFailure,
  timeout) and the command of `settings.json` with the agent name as its argument. (test:
  `tests/test_agent_files.py::test_hook_entry_has_no_matcher_no_if_one_handler`,
  `tests/test_agent_files.py::test_handler_equals_settings_handler_except_the_argument`,
  `tests/test_agent_files.py::test_command_is_settings_script_path_plus_agent_name`)
- The file name, the `name` and the argument are one word, and it is an agent that the hook knows. (test:
  `tests/test_agent_files.py::test_file_name_equals_name_equals_argument`)
- The line that a file carries blocks a forbidden call and allows an allowed one when a shell runs it, from the project root and
  from another directory. (test: `tests/test_agent_files.py::test_each_file_own_command_blocks_and_allows_through_bash_c`)
- An entry with no matcher fires on every tool call of its agent (a claim of the Claude Code documentation, not tested), so the hook
  sees tools that Claude Code might add itself; it refuses every tool name it does not know, among them the internal tool names of
  the documentation, with one exception: `SubagentHandback`, the internal tool by which a subagent returns its final message
  (observed once, not documented; see "Observations"). The hook allows it (exit 0, silent) for the two agents and for no other name;
  the settings matcher does not contain it. (test: `tests/test_agent_files.py::test_matcherless_entry_gets_refused_tool_names`,
  `tests/test_agent_files.py::test_subagent_handback_is_allowed_in_process_and_through_the_files_own_line`,
  `tests/test_agent_files.py::test_a_second_internal_name_is_still_refused_with_the_tool_named`,
  `tests/test_agent_files.py::test_subagent_handback_is_not_in_the_settings_matcher`,
  `tests/test_agent_files.py::test_an_unknown_agent_name_gets_no_allowance_for_the_handback`)
- The documentation's example of a `tools` list says that such a subagent cannot use MCP tools, and it is silent on the PowerShell
  tool and on tools that Claude Code adds itself (ToolSearch, TodoWrite). Whatever a `tools` list grants, the hook refuses
  PowerShell and every name it does not know except `SubagentHandback`; the refusal of an unknown tool names the tool and points
  to this document. (test: `tests/test_restrict_writes.py::test_every_other_tool_is_refused`; what a
  `tools` list grants is a claim of the Claude Code documentation, not tested)
- Whether Claude Code honours `shell` and `onFailure` in the frontmatter hooks of a subagent is inferred from its documentation (the
  same format as settings hooks) and was not tested. (not tested)
- Nothing in the files can widen the hook: the agents that the hook knows are the agent files; the script path is the same in both
  files and in `settings.json`; every tool that the settings matcher or a file can route to the hook is refused with the worst call
  of its kind, the three read tools and `SubagentHandback` apart; every tool a file lists besides the read tools is matched by the settings entry. (test:
  `tests/test_agent_files.py::test_agent_files_cannot_widen_the_hook`)
- **A matcherless entry starts the hook on every tool call of its agent, Read, Glob and Grep included.** Measured once on this Windows
  machine, not for CI (15 runs, medians): one start of the script took 94 to 141 ms; a call that both the settings entry and the
  frontmatter copy see took 156 ms (in parallel) to 237 ms (one after the other). (not tested)
- The prompts say that they are instructions, not enforcement, contain no word of enforcement, and end with a "Next, for you" line
  that tells the person which `bt approve` command to run. (test: `tests/test_agent_files.py::test_prompts_say_instructions_not_enforcement`,
  `tests/test_agent_files.py::test_prompts_have_no_enforcement_words`, `tests/test_agent_files.py::test_prompts_end_with_next_for_you`)

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
  `tests/test_restrict_writes.py::test_the_coder_may_validate_and_check`,
  `tests/test_restrict_writes.py::test_the_signal_check_of_the_coder_has_one_form`)
- Neither agent writes in the other's folder, in `approvals/`, `src/`, `tests/`, `docs/`, `.claude/` or anywhere else, and every other
  command is refused. (test: `tests/test_restrict_writes.py::test_the_coder_may_not_write_anywhere_else`,
  `tests/test_restrict_writes.py::test_the_architect_may_write_nothing_else`,
  `tests/test_restrict_writes.py::test_the_two_agents_do_not_share_a_folder`,
  `tests/test_restrict_writes.py::test_every_other_command_is_refused`)
- Read, Glob and Grep get no objection: **the agents can read any file that Claude Code may read.** The hook limits what they write
  and run, not what they read. (test: `tests/test_restrict_writes.py::test_read_glob_and_grep_get_no_objection`)
- A relative path is resolved against `CLAUDE_PROJECT_DIR` of the environment, and, if that is unset, against the `cwd` field of
  the call; with neither the call is refused. (test: `tests/test_restrict_writes_protocol.py::test_the_environment_wins_over_the_cwd_of_the_call`,
  `tests/test_restrict_writes_protocol.py::test_no_project_directory_is_blocked_and_the_cwd_of_the_call_is_the_fallback`)
- A Bash command passes only if every character is a letter, a digit, `_`, `.`, `/`, `-` or a single space between words. A
  backslash is refused with its own reason, so paths are written with forward slashes. Quotes, globs, `$`, backticks, `;`, `&`, `|`,
  `<`, `>`, newlines and tabs, environment prefixes and `cd x &&` are refused. The agents use the Bash tool (Git Bash on Windows);
  every PowerShell call by them is refused. (test: `tests/test_restrict_writes.py::test_a_backslash_is_refused_with_its_own_reason`,
  `tests/test_restrict_writes.py::test_a_shell_character_gets_the_allowlist_reason`,
  `tests/test_restrict_writes.py::test_every_other_tool_is_refused`)
- The hook ignores `run_in_background` and `dangerouslyDisableSandbox` in the input of a call: it decides on the command alone, and
  `bt signal check` is asked by the ask rule anyway. (not tested)

Each refusal of a path has one test, named in its row. (test:
`tests/test_agents_docs.py::test_every_row_of_the_refusal_table_names_a_test`)

| Refusal | Test |
|---|---|
| `..` in a path, also when the path lands in the folder | `tests/test_restrict_writes.py::test_a_path_with_dot_dot_is_refused_even_when_it_lands_in_the_folder` |
| an absolute path outside the project | `tests/test_restrict_writes.py::test_an_absolute_path_outside_the_project_is_refused` |
| a link or junction from the folder to somewhere else | `tests/test_restrict_writes.py::test_a_junction_or_link_from_the_folder_to_somewhere_else_is_refused` |
| a file that is itself a link elsewhere | `tests/test_restrict_writes.py::test_a_file_whose_real_path_is_somewhere_else_is_refused` |
| UNC and device paths | `tests/test_restrict_writes.py::test_unc_and_device_paths_are_refused` |
| an NTFS stream | `tests/test_restrict_writes.py::test_an_ntfs_stream_is_refused` |
| a component that ends in a dot or a space | `tests/test_restrict_writes.py::test_a_trailing_dot_or_space_is_refused` |
| an 8.3 short name below the project | `tests/test_restrict_writes.py::test_an_8_3_short_name_is_refused` |
| a path relative to a drive (`C:x`) | `tests/test_restrict_writes.py::test_a_path_relative_to_a_drive_is_refused` |
| wildcard and reserved characters | `tests/test_restrict_writes.py::test_wildcards_and_reserved_characters_are_refused` |
| a name outside the id rules (uppercase, device name, built-in id) | `tests/test_restrict_writes.py::test_the_id_rules_apply_to_the_file_name` |
| a folder in the wrong case, where the system tells case apart | `tests/test_restrict_writes.py::test_a_wrong_case_in_the_folder_is_the_same_folder_only_where_the_system_says_so` |
| the same, for a folder that does not exist yet | `tests/test_restrict_writes.py::test_a_wrong_case_folder_that_does_not_exist_yet_is_the_folder_only_where_the_system_says_so` |

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
- **The signal coder may run `bt signal check` only in the default permission mode; the hook refuses it otherwise (enforced).** The
  hook cannot see whether an agent runs in the background; whether Claude Code shows the ask prompt to a person for a background
  agent in the default mode was not tested. The ask rule is a second layer. A run in any other mode, with the field missing or with a
  value that is not text, is refused with its own reason, and the architect's refusal of the command is the same in every mode. (test:
  `tests/test_restrict_writes.py::test_the_coder_runs_signal_check_only_in_the_default_mode`,
  `tests/test_restrict_writes.py::test_the_architects_refusal_of_signal_check_is_the_same_in_every_mode`,
  `tests/test_restrict_writes_protocol.py::test_the_coders_signal_check_runs_only_in_the_default_mode`,
  `tests/test_restrict_writes_commandline.py::test_the_coders_signal_check_through_the_command_lines_needs_the_default_mode`; the
  background case is not tested)
- An agent that runs the command runs its own code with its own permissions, as it could with Python; the only limit of an agent
  run is the timeout of its own tool. The subprocess hardening, a wall-clock limit and a memory limit, is NOT built
  ([ADR 0018](adr/0018-coded-signals-and-approval-gate.md), addendum, known gap 6). (test:
  `tests/test_agents_docs.py::test_the_binding_sentences_of_the_adr_are_kept`)
- Whether Claude Code shows the ask prompt in `auto`, with `dontAsk` or under `bypassPermissions` was not tested, which is why the
  hook refuses those modes. **The background case is not covered by the mode check**: the hook cannot see it. (not tested)
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
  expands the variable is a claim of its documentation, not tested; in these tests it is a Windows path on Windows)
- Without the variable an agent call exits 2 (Python exits 2 for a script it cannot open) and a main-session call exits 0. (test:
  `tests/test_restrict_writes_commandline.py::test_without_the_project_directory_variable_an_agent_call_exits_2_and_the_main_session_0`)
- **The hook needs Git Bash (`"shell": "bash"`) and `uv` on the `PATH`.** (test:
  `tests/test_restrict_writes_commandline.py::test_the_settings_entry_has_the_shape_the_design_needs`,
  `tests/test_restrict_writes_commandline.py::test_a_broken_environment_blocks_only_where_the_hook_is_needed`)
- **Why `uv run --no-project python -I`.** On the development machine `uv.exe` is a real executable and runs a Python 3.12, from the
  project folder and from another one, while `python` is a 3.13 next to a Windows Store stub. `-I` ignores `PYTHONPATH` and the
  script directory; `--no-project` avoids a sync. The documentation does not recommend one of `python`, `py` and `uv run python`.
  (not tested)
- The entry has `"onFailure": "block"` and a timeout of at most 60 seconds (the file has 30). (test:
  `tests/test_restrict_writes_commandline.py::test_the_settings_entry_has_the_shape_the_design_needs`)
- Cost, measured once on this Windows machine, not for CI (Windows 11, 15 runs each, medians): about 50 ms for a main-session call,
  94 to 141 ms for one start of the script, 156 ms (parallel) to 237 ms (one after the other) for two starts. (not tested)

## When the hook breaks

- **While the entry is removed or broken, the agents are not fenced for writes.** The deny and ask rules restrict only `bt approve`
  and `bt signal check`; nothing else stops an agent from writing a file. Do not run the agents until the entry works again. (not
  tested)
- **`uv` or the interpreter is missing.** Calls of the two agents exit 127 and are blocked because of `onFailure`; the main session is
  not touched. A script file that is missing exits 2, which blocks even without `onFailure`; so does an error of `uv` itself (`uv`
  exits 2 for its own errors). Only an exit 1 or 127 needs `onFailure`. Fix `uv`, or remove the entry: delete the `"hooks"` key of
  `.claude/settings.json`; the deny and ask rules stay. (test:
  `tests/test_restrict_writes_commandline.py::test_a_broken_environment_blocks_only_where_the_hook_is_needed`,
  `tests/test_restrict_writes_commandline.py::test_without_the_project_directory_variable_an_agent_call_exits_2_and_the_main_session_0`;
  the exit code of `uv` is not tested)
- **Git Bash itself is missing.** The entry has `"shell": "bash"`: if the shell cannot start, `onFailure` blocks the calls of the main
  session too, and the only way out is to remove the entry. (not tested)
- **The hook blocks something it should allow.** Read the reason on stderr (`restrict_writes: blocked: ...`). The tables of "What
  each agent may do" say what is allowed; change the hook and its table test together. (test:
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

## Observations

Seen by the maintainer on Claude Code 2.1.318, on one machine. The first two were seen with a logging hook and a user-level probe
agent; the rest in probes of the two real agents with this script, in a clone outside the repository, in `auto` mode. In the probe
clone a second, logging handler was added beside the signal coder's frontmatter copy; the architect's copy had none. **Each is
observed once, Claude Code 2.1.318, one machine, not a test.** (not tested)

- A settings-level hook receives `agent_id` and `agent_type` for a subagent call, also for a background one; `agent_type` is the name
  from the agent file. A main-session call has neither. Every call carries `permission_mode`. (not tested)
- `"onFailure": "block"` blocked a Write when the hook exited 1; the same hook without the key only gave a warning and the write went
  through. (not tested)
- On calls of the two real agents the settings entry received `agent_type`, `agent_id` and `permission_mode`; so did the logging
  handler beside the signal coder's frontmatter copy. This was not observed for the architect's frontmatter copy. Every
  `permission_mode` seen was `auto`. (not tested)
- The settings entry refused the signal coder's Write to `src/`, the architect's `bt signal check` and, in `auto` mode, the coder's
  `bt signal check`, and it allowed the Write to `strategies/signals/` and to `strategies/drafts/`. (not tested)
- The logger beside the signal coder's frontmatter copy saw Read, Write, Bash and `SubagentHandback` calls of the coder. For the
  architect we know only that its copy fired and refused the handback. A Glob call of the coder was not observed. (not tested)
- **`SubagentHandback`.** Claude Code gives every subagent an internal tool of this name, with a `message` field, by which the
  agent returns its final message. It is not in the `tools` list of the files and not in the documentation we read. The frontmatter
  copy saw it (the settings entry did not, because of its matcher). Before the fix the hook refused it ("may not use
  SubagentHandback: the hook does not know it"), and every background agent ended without returning a result: the architect after 4
  attempts, the coder after 5 to 9: the agents retried the refused handback 4 to 9 times each. The hook now allows it for the two
  agents. (not tested; the allowance is tested with a payload of the observed shape)
- After the fix (clone at commit `5c0d8b2`, `uv` on the PATH, session in `auto` mode): the architect's draft came back with its
  assumptions and open questions, and its validate was `uv run bt validate`; the coder's `uv run bt signal check` was refused with
  "permission_mode is 'auto': the signal coder may run bt signal check only in the default permission mode" (no advice to switch);
  the coder reported that it did not retry or work around the refusal and named the check as a step for the person; and the
  coder's read of `README.md` came back. So the handback allowance works. (not tested)
- Every subagent started from the main session ran in the background, in every probe; the main session said (its own statement)
  that it had no way to ask for a foreground run. (not tested)
- `bt` alone was not on the PATH of the agent (exit code 127); the agent then ran `uv run bt validate ...`, which the hook allowed.
  The prompts now name the `uv run bt ...` spelling. (not tested)
- None of the agents retried the refused Write or the refused Bash test call; they did retry the refused handback. (not tested)
- The default mode was not reached: every session of the maintainer showed `permission_mode` `auto` (in the logs and as "Allowed by
  auto mode"), no setting for it was found in the user `settings.json`, in a managed settings file (none exists) or in the project
  settings, and whether the mode can be switched on this machine was not established. (not tested)
- With `uv` on the PATH, each of the three agents called `SubagentHandback` once and the result came back (the architect: Read,
  Glob, Read, Write, Bash, handback; the coder's check: Bash, handback; the `README.md` reader: Read, handback). With `uv` removed
  from the PATH of the window, the signal coder asked to read `README.md` called `SubagentHandback` 4 times, was resumed by the main
  session (SendMessage), read `README.md` again and called it 4 more times: the retry pattern of the refused handback before the
  fix. The main session read the file itself. The settings entry does not match Read or `SubagentHandback`, so only the frontmatter
  copy can have blocked those calls. That is strong evidence, not proof (the text of the blocked result was not captured, and the
  agent's transcript was empty), that Claude Code honours `"onFailure": "block"` in a frontmatter hook when `uv` fails (exit 127).
  Whether it honours `shell` there is not separately established. (not tested)
- In all runs the only internal tool name seen on agent calls was `SubagentHandback`; `Agent`, `ToolSearch` and `SendMessage`
  appeared only with `agent_type` null (the main session). (not tested)

**Not observed:** the default mode, the ask prompt (and so whether a prompt reaches a person for a background agent), a foreground
agent, the `acceptEdits` and `plan` modes, the payload that the architect's frontmatter copy receives, and a Glob call of the
coder. (not tested)

## Details of the hook

These paragraphs are separate on purpose: each states one detail that may change, with its test. (not tested)

The tools the hook sees. The settings entry matches Write, Edit, MultiEdit, NotebookEdit, Bash and PowerShell: the hook sees six
tools, and the rest of what an agent can do is limited by the `tools:` list of its file and, for the frontmatter copy, which has no
matcher, by the hook. For the two agents the hook decides on the first three by path and on Bash by command, allows Read, Glob and
Grep and `SubagentHandback` (the way a subagent returns its message, see "Observations"), and refuses NotebookEdit, PowerShell and
every other tool name it is given. (test: `tests/test_restrict_writes.py::test_the_internal_handback_tool_is_allowed_and_a_second_internal_name_is_not`,
`tests/test_restrict_writes_commandline.py::test_the_settings_entry_has_the_shape_the_design_needs`,
`tests/test_restrict_writes.py::test_every_other_tool_is_refused`,
`tests/test_restrict_writes.py::test_read_glob_and_grep_get_no_objection`)

The permission mode. The signal coder's `bt signal check` is allowed only when `permission_mode` of the call is `default`; any other
value, a missing field or a value that is not text is refused with its own reason. `bt validate` and every write ignore the mode.
(test: `tests/test_restrict_writes.py::test_bt_validate_is_allowed_in_every_permission_mode`,
`tests/test_restrict_writes.py::test_a_write_does_not_depend_on_the_permission_mode`,
`tests/test_restrict_writes_protocol.py::test_a_write_and_a_validate_do_not_depend_on_the_permission_mode`,
`tests/test_restrict_writes_protocol.py::test_a_signal_check_without_a_permission_mode_is_blocked`)

The 8.3 rule. A path component below the project directory with `~` followed by a digit, such as `RSIPUL~1.py`, is refused. The
project directory itself may have a short name (the temporary folders of CI runners do). (test:
`tests/test_restrict_writes.py::test_an_8_3_short_name_is_refused`,
`tests/test_restrict_writes.py::test_the_8_3_guard_looks_below_the_project_directory_only`)

Stdin decoding. The script reads the bytes of stdin and decodes them as UTF-8 itself; bytes that are not valid UTF-8 are refused with
their own reason. The code page of the console is not asked. On the development machine, in the form `uv run --no-project python -I`
with piped input, `sys.stdin.encoding` was cp1252 with `errors` set to `surrogateescape`, so the byte 0x81 did not raise: it became
a lone surrogate. (test: `tests/test_restrict_writes_protocol.py::test_stdin_that_is_not_utf8_is_blocked_with_its_own_reason`,
`tests/test_restrict_writes_protocol.py::test_a_raw_utf8_file_name_is_shown_escaped_from_the_bytes_not_from_a_code_page`,
`tests/test_restrict_writes_protocol.py::test_content_with_the_bytes_c3_81_is_accepted`; the cp1252 reading is an observation, not
tested)

## Known gaps

- Internal tool names are observed, not documented. `SubagentHandback` was seen once and is allowed by name. A Claude Code update
  that adds another internal tool makes the hook refuse it (fail closed by design). The hook's message, which names the tool, goes
  to the agent: the person sees an agent that ends without a result, and finds the message in the agent's transcript. The fix is a
  decision of the maintainer, a new named constant and a test. (not tested)
- A spelling that the rules do not match is not denied. The table above gives examples; `GAPS` in
  `tests/test_agent_deny_rules.py` is the list. (test: `tests/test_agent_deny_rules.py::test_the_known_gaps_are_not_matched`)
- Read, Glob and Grep are not restricted to paths: an agent can read `.env`, `approvals/` and any other file that Claude Code may
  read, and no `Read` deny rule is set. (test: `tests/test_restrict_writes.py::test_read_glob_and_grep_get_no_objection`; what a
  read exposes is not tested)
- A matcherless entry costs a hook start on every tool call of an agent (see "The agent files"). (not tested)
- The hook is a fence: a person who can write to `.claude/` can remove it, and an agent that gets a tool the hook does not know
  would be refused only by this hook. Whether `Bash` in an agent's `tools` also grants PowerShell, and whether MCP tools are
  inherited, is not documented. (not tested)
- The settings entry decides by `agent_type`. If Claude Code sends another value for an agent than its file name, the settings entry
  gives no decision for it and only the frontmatter copy, in a trusted folder, holds. (not tested)
- The permission mode is the mode of the session; the hook does not know whether a prompt will reach a person, and it cannot see
  whether an agent runs in the background. (not tested)
- The static check is a tripwire, not a sandbox, and `bt signal check` runs unapproved code (known gaps of
  [ADR 0018](adr/0018-coded-signals-and-approval-gate.md)). (not tested)

## Tests

The tests of this document are `tests/test_agent_deny_rules.py`, `tests/test_restrict_writes.py`,
`tests/test_restrict_writes_protocol.py`, `tests/test_restrict_writes_commandline.py`, `tests/test_agent_drafts_ignored.py` and
`tests/test_agents_docs.py`. The mutation tables of the pull request are in its report, not in the repository.
