# 0019: The agents and what keeps them inside the gate

- **Status:** Accepted. Built in Phase 10 part 4a: the deny and ask rules, the hook and the git-ignored drafts folder. The agent
  files, the example specs and the end-to-end test are part 4b. Details, spellings and the tests that check each claim:
  [agents.md](../agents.md).

## Context

[ADR 0018](0018-coded-signals-and-approval-gate.md) made approval a decision of a person: `bt approve` reads the code, prints it
and archives the bytes that were shown. It left two questions to the agents part (its addendum, binding): may an agent run
`bt signal check`, which executes a file that nobody approved, in the process of the command, with the permissions of whoever runs
it and no time or memory limit; and what stops an agent that has a shell from running `bt approve` itself, so that the approval
means nothing. The addendum also fixed the wording: an agent that runs the command runs its own code with its own permissions, the
only limit of an agent run is the timeout of its own tool, and the subprocess hardening (a wall-clock limit and a memory limit) is
NOT built.

What Claude Code offers, as far as its documentation says (checked, not tested by us): permission rules that match the text of a
command (not a security boundary; a full path, `sh -c` and a quoted word are named as not caught); hooks that run before a tool call
(only exit code 2 blocks, any other failure lets the call through unless the hook says `"onFailure": "block"`, which needs 2.1.295
or later); hooks in `settings.json` that run also with `-p` and in an untrusted folder, while hooks in the frontmatter of a project
agent are skipped until the folder is trusted; and an `agent_type` in the input of a call made inside a subagent. Observed by the
maintainer on 2.1.318, on one machine, with a logging hook and a probe agent, not with this script on one of the two agents: a
settings-level hook gets `agent_id` and `agent_type` (the name from the agent file) for a subagent call, also a background one, none
in the main session, and `permission_mode` on every call; and `"onFailure": "block"` blocked a write when the hook exited 1, while the
same hook without the key only warned.

## Decision

**Two fences, and a person.** A blocklist of spellings of `bt approve` can never be complete, so the rule is a tripwire and the hook
is an allowlist. Neither is a boundary; the person who reads the code before `bt approve --code --sha` is the defence that counts.

- **Deny and ask rules in `.claude/settings.json`.** `bt approve` is denied in the spellings `bt`, `uv run bt`, `bt.exe`, a path
  before `bt` or `bt.exe`, and `python -m`, `py -m` and `python3 -m backtest_agent`, for the Bash and for the PowerShell tool. The
  wide rules use a leading `*`, whose meaning is not documented, so the plain forms stay as redundancy on purpose. `bt signal check`
  is in the `ask` list for both tools. The rules also apply to Claude Code's own session; the person runs `bt approve` in their own
  shell. A test reads the rules and checks a table of spellings against a reference matcher that is our reading of the documented
  syntax, not Claude Code's matcher, plus the spellings that are known not to match.
- **A hook, `.claude/hooks/restrict_writes.py`, as an allowlist for each agent.** The strategy-architect may write only
  `strategies/drafts/<name>.yaml` and run only `bt validate` of a draft. The signal-coder may write only
  `strategies/signals/<id>.py` and `<id>.cases.yaml` and run `bt validate` and `bt signal check`. A Bash command passes only as an
  exact sequence of words made of letters, digits, `_`, `.`, `/`, `-` and single spaces; everything else, a backslash included, is
  refused. Read, Glob and Grep get no objection. The hook reads the bytes of stdin and decodes them as UTF-8 itself. It exits 0
  without output or exits 2 with a reason, and **never prints a `permissionDecision`**, because an "allow" could skip the ask rule.
  It fails closed: an error of the script is exit 2.
- **Registered in `settings.json` and, with part 4b, in the frontmatter of each agent.** The `settings.json` entry runs also with
  `-p` and in an untrusted folder, carries `"onFailure": "block"` (a script that cannot start would otherwise let the call through)
  and decides by the `agent_type` of the call; a call without it, or of another agent, gets no decision, and the shell line does not
  even start `uv` for it, so the main session cannot be blocked by a broken `uv`. The frontmatter copy takes the agent name as an
  argument and does not depend on `agent_type`; it is a second layer for a trusted folder. Both fire for an agent call; the measured
  cost of two starts is under a quarter of a second.
- **`bt signal check`: the coder may, the architect may not.** The signal coder may run `bt signal check` only in the default
  permission mode; the hook refuses it otherwise (enforced). The hook cannot see whether an agent runs in the background; whether
  Claude Code shows the ask prompt to a person for a background agent in the default mode was not tested. The ask rule is a second
  layer. The hook allows the exact forms for the coder only when `permission_mode` of the call is `default`, and refuses any other
  value, a missing field or a value that is not text, each with its own reason; the architect's refusal is the same in every mode,
  and `bt validate` and every write ignore the mode. Whether Claude Code shows the prompt in `auto`, with `dontAsk` or under
  `bypassPermissions` was not tested, which is why the hook asks for the default mode. The background case is NOT covered by the mode
  check. The agents should not
  be run with `bypassPermissions`, and whether hooks run there was not tested either. As ADR 0018 says, an agent that runs the command
  runs its own code with its own permissions, the only limit of an agent run is the timeout of its own tool, and the subprocess
  hardening is NOT built.
- **Drafts are private, signals are public.** `strategies/drafts/` is git-ignored except `.gitkeep`. `strategies/signals/` and
  `approvals/` stay tracked, because a fresh clone has to reproduce a logged run; a person adds a signal file to git only after
  reading the code.

**Rejected.**

- *Only a deny rule.* It misses `sh -c`, a full path and a quoted word, and nothing limits what else an agent runs.
- *Only the frontmatter hook.* It is skipped silently in an untrusted folder and with `-p`, and the agent files do not exist before
  part 4b.
- *Dispatch by `agent_type` alone.* If Claude Code sends a value other than the file name, the settings entry would give no decision
  for the agent; the frontmatter copy covers that case in a trusted folder.
- *`shlex` and a blocklist of shell characters for Bash.* `shlex` in POSIX mode eats backslashes; a character allowlist with an
  exact grammar is stricter and shorter.
- *Running `bt signal check` for the agents in a subprocess with limits.* NOT built (ADR 0018, addendum).
- *The Python on the path (`python` or `py`).* On the development machine `python` is a 3.13 next to a Windows Store stub; `uv.exe`
  is a real executable and runs the project's Python 3.12. The documentation does not recommend one.

## Known gaps

1. The rules are text rules; a spelling that is not listed is not denied.
2. `bypassPermissions`: whether hooks and ask rules hold is not documented and was not tested. The agents should not be run in it.
   The permission mode is the mode of the session: the hook cannot know whether a prompt will reach a person, and it cannot see a
   background agent (the background case is NOT covered by the mode check).
3. The hook is a fence a person can remove; it is not a boundary. The static check is a tripwire; `bt signal check` runs unapproved
   code in the process of the command (ADR 0018, gap 6).
4. A hook that cannot start is a block only because of `"onFailure": "block"`, which is in the Claude Code documentation (2.1.295
   or later) and not in the SchemaStore schema. The documentation does not say what an older version does with an unknown key; the
   whole `settings.json`, deny rules included, might be skipped.
5. `agent_type` is the only key of the settings entry. The frontmatter copy needs the workspace trust.
6. Whether the `Bash` entry of a `tools` list also grants PowerShell, and whether MCP tools are inherited, is not documented.

## Consequences

- An agent that follows its prompt, and one that does not, meet the same fences. A person who wants a signal in the repository reads
  its code and runs `bt approve` in their own shell.
- The main session also cannot run `bt approve`, and it is asked before every `bt signal check`.
- A new spelling or a new allowed command needs a row in a table test and a mutation table; `tests/test_agents_docs.py` fails when
  `docs/agents.md` names a test that does not exist or makes a claim with neither a test nor `(not tested)`.
- Part 4b adds the agent files, three example specs, fake agents and an end-to-end test without a real model; the hook is then run
  on scripted calls, never yet on a call of a real agent.
