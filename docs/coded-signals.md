# Coded signals

A **coded signal** is a signal function that an agent writes after the maintainer approved the idea behind it. The engine
never trusts it: the code is hashed, archived, checked statically and checked against the signal contract before it runs,
and nothing is imported before it was approved. The project is educational and not investment advice. The decisions are in
[ADR 0018](adr/0018-coded-signals-and-approval-gate.md); the signal contract itself is in
[strategy-spec.md](strategy-spec.md); the counting of trials is in [journal.md](journal.md).

> **Public.** Everything described here is tracked in git, so it is public in this repository: `strategies/signals/*.py`,
> their `cases.yaml`, every file in `approvals/` (records and archived code) and the briefs inside the specs. Never put
> anything private in a brief or in code.

This document describes what exists after Phase 10 part 3b: the `coded` block of the spec, the hashes, the approval
records, the static check, the gate that loads approved code, the check before a run, the `cases.yaml` format, the commands
`bt approve` and `bt signal check` and the handling of a coded spec in `bt run`, `bt validate`, `bt data fetch` and `bt report`.
The agent files come with part 4b of the phase ([agents.md](agents.md)); where this document mentions them it says so.

## What is approved

Two things are approved, one after the other, by a person.

- **The idea** is the signal id and the brief: `{signal_id, brief}`. The brief says in plain language what the signal does,
  what every parameter means and how much history it needs. Params, universe, period, costs, execution, sizing, name and
  description are **not** part of the idea. They are validated by the params model of the code at every run, and every run
  is journaled; a changed parameter is a new variant and counts as a trial ([journal.md](journal.md)).
- **The code** is the SHA-256 of the source after CRLF is turned into LF (UTF-8, no byte order mark). Code is approved only
  for an approved idea, and only if it passes the static check.

### The hashes, byte for byte

The idea hash is the SHA-256 of the canonical JSON of `{"brief": ..., "signal_id": ...}` (sorted keys, no spaces, ASCII
only; the same function as `run.json`), as UTF-8 bytes. The brief has CRLF turned into LF and nothing else done to it, so
leading and trailing spaces count.

| Id | Brief | Hashed bytes | SHA-256 |
|---|---|---|---|
| `rsi_pullback` | `Buy when RSI(14) < 30.` | `{"brief":"Buy when RSI(14) < 30.","signal_id":"rsi_pullback"}` | `5c4e9e9af8ed5b0f84bf6d4e5b3aec9391a08a374335db9c115121536625a55f` |
| `x_signal` | `a`, CRLF, `b` | `{"brief":"a\nb","signal_id":"x_signal"}` (the `\n` is the JSON escape of the LF) | `9ba96a0c177373ed575249d1402cc33668c4b05f98d2bf3de0d055522d0631d2` |
| `x_signal` | ` x ` with its spaces | `{"brief":" x ","signal_id":"x_signal"}` | `df46de2a17dc90b8d306d9ce73831b850628a940f02ab8fce4aff6c874319e2c` |
| `x_signal` | `B` | `{"brief":"B","signal_id":"x_signal"}` | `deba52ffffb76ac1a954fd11e28370ea6cbf9afeca4358901fe3d7b0050cdebc` |

The code hash of the two bytes lines `x = 1`, LF, `y = 2`, LF (a file with CRLF line ends hashes the same) is
`8353afe579a16d27abc038055bf713459ba6ef418c65b143b526a09dd529e500`. A file without a final line break is hashed as it is:
the five bytes `x = 1` give `8ff436def1451285599a1b1ad70800493b8dcafde2912e1a38345633054e4c26`. All of these were computed
with `hashlib` and written out by hand, not with project code, so you can recompute them.

## Approving: `bt approve`

Approval is a decision of a person, made in two steps with `bt approve SPEC` ([cli.md](cli.md), "`bt approve SPEC`"):

1. `bt approve SPEC --idea` approves the idea `{signal_id, brief}` of the spec and appends it to `approvals/<id>.json`.
2. `bt approve SPEC --code` reads `strategies/signals/<id>.py` once and, if the idea is approved and the static check passes,
   prints the whole file with line numbers, its size and its hash and stops with exit code 8. The person reads it and repeats
   the command with `--sha` and the first 8 hex characters of the hash. Only then are the bytes that were shown archived and
   listed for the idea. A missing or different `--sha` shows the review again and writes nothing.

The command never imports, compiles or executes the file, and it never edits the spec. Code can only be approved for an
approved idea, and an idea without approved code runs nothing. Approving the same idea or the same code again changes nothing.

**Who may run `bt approve`.** A person, and a person must read the printed code: the command cannot check that anybody did. An
agent with a shell could run both steps itself and the approval would mean nothing, so the agent that writes a signal must not
run `bt approve`. Two fences stand in the way of an agent ([agents.md](agents.md)): a deny rule in `.claude/settings.json` for
`bt approve` in the spellings listed there, and the hook of the agents, which lets them run only `bt validate` and, for the signal
coder, `bt signal check`. Neither is a boundary; the person who reads the code is. An approval means that a person read this code. It
does not make the code safe: the static check is a tripwire and not a sandbox (below, and the known gaps of the ADR).

## The coded block of a spec

```yaml
signal:
  id: rsi_pullback
  params:
    window: 14
    entry_below: 30
  coded:
    brief: >
      Hold a symbol while its 14-row RSI is below entry_below. window is the RSI length in trading rows of the symbol;
      entry_below is the RSI level. Needs window rows of history.
```

- **Id.** Lowercase letters, digits and underscores, starting with a letter, at most 64 characters. It must not be the id of
  a built-in signal and not one of the 22 names that Windows reserves for devices (`con`, `prn`, `aux`, `nul`, `com1` to
  `com9`, `lpt1` to `lpt9`), because the id is a file name. The path of the code is **derived** from the id
  (`strategies/signals/<id>.py`); a spec never names a path.
- **Brief.** 1 to 2000 characters after CRLF becomes LF, with at least one character that is not white space. No character
  of the Unicode categories Cc, Cf, Zl or Zp except a line break and a tab (control characters, invisible format characters
  such as zero-width spaces and right-to-left marks, and the Unicode line and paragraph separators). They hide text from a
  reader, and the same rule applies to source code and to every file of this repository (a test scans them).
- **Params.** Numbers, text, true or false, or lists of those; names are text. No null, no nested block, no NaN or infinity.
  There is no params model before the code exists, so nothing else is checked when the spec is read.
- **Not looked up.** A spec with a `coded` block is valid before its code exists. The signal is not in the registry, and
  `params_model()` and `warmup_rows` of an unresolved spec (one without `coded.code_sha256`) raise `UnknownSignalError`
  **whatever the registry holds**, so an unresolved spec can never run.
- **What a run stores.** `run.json["spec"]["signal"]` holds `id`, `params` and `coded` with `brief` and `code_sha256` (the
  sha is set when the gate resolves the spec). Because the sha is part of `StrategySpec.to_dict()`, it is part of the
  variant hash: **rewriting the code is a new variant of the same family** (the family is the id), and the trial counter
  stays honest. A spec without the block serializes exactly as before (the pinned digest of
  [journal.md](journal.md) is unchanged).

## Files and folders

| Path | What | Written by |
|---|---|---|
| `strategies/signals/<id>.py` | the candidate code, editable | a person, or the signal-coder agent (the hook lets it write only here) |
| `strategies/signals/<id>.cases.yaml` | hand-calculated examples as data (see `cases.yaml` below) | a person, or the signal-coder agent |
| `approvals/<id>.json` | the append-only approval history of one signal id | `bt approve` |
| `approvals/code/<sha256>.py` | the approved code, LF line ends; the file name is its hash | `bt approve` |
| `approvals/.lock` | exists only while an approval runs; git-ignored | `bt approve` |

The archive is what runs, not the editable file: the gate reads the archived bytes once, checks their hash and runs exactly
those bytes, so nothing can change between the review and the run, and an old run can be reproduced after the working file
was edited. That is why the archive is tracked: a fresh clone must be able to reproduce a logged run. The cost is that
approved code is public.

## The approval record

`approvals/<id>.json` is canonical JSON like `run.json` (sorted keys, no spaces, ASCII, one trailing LF, UTF-8). It is a list
of idea entries, one per idea hash, each with the code hashes approved for it. **Nothing is ever overwritten or removed.**

- Approving an idea that is already approved, or code that is already approved for its idea, is a no-op: nothing is written
  and the first timestamp stays.
- A changed brief is a new idea, so it adds a new entry with no code. Earlier entries and their code stay, so a stored run
  still reproduces. Going back to an old brief finds its old entry.
- Changed code adds a hash to the entry of its idea, in order; the last one is the latest.
- Timestamps are UTC with whole seconds and come from the caller's clock. No user name, no path and no machine is ever
  written (a test scans the written files).
- The brief you approve is checked by the same function as the spec (`check_brief`), so an idea the spec would refuse is
  refused and nothing is written.

A worked example. The idea `x_signal` with the brief `B` is approved at 10:00:00, then this source, which is
`strategies/signals/x_signal.py`, at 11:00:00 (the block is marked `text` so that `ruff format` does not touch it: its bytes are
hashed):

```text
"""A signal that is scaled by a constant."""
from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal


@register_signal("x_signal", params=SignalParams)
def x_signal(prices, params):
    return per_symbol_signal(prices, lambda close: close * 0.0)
```

Its code hash is `83e18fb4daa4d96e203d83fa9f17c1b28c183c44fb75c677db99eabd8ffa5370`, and the record file is this one line:

```json
{"ideas":[{"approved_at":"2026-11-02T10:00:00Z","code":[{"approved_at":"2026-11-02T11:00:00Z","sha256":"83e18fb4daa4d96e203d83fa9f17c1b28c183c44fb75c677db99eabd8ffa5370"}],"idea_sha256":"deba52ffffb76ac1a954fd11e28370ea6cbf9afeca4358901fe3d7b0050cdebc"}],"schema_version":1,"signal_id":"x_signal"}
```

`tests/test_coded_docs.py` runs this example and compares it with the document.

### Why LF

Approved code is hashed byte for byte. A file whose line ends change on checkout (CRLF on Windows) would no longer match
its hash, and a gate that refuses it would refuse correct code. So `.gitattributes` makes `approvals/**` and
`strategies/signals/*.py` LF in the working tree on every system (a test parses the file), the hash is taken after CRLF is
turned into LF so an editor that saves CRLF does not change the approval, and ruff is told to leave those folders alone
(`extend-exclude` in `pyproject.toml`), because `ruff format` would rewrite reviewed bytes and `ruff check` would lint code
that an agent wrote.

### The lock

An approval reads the record, changes it and writes it back. Two at once could lose an entry, or both write the same
temporary file. So an approval takes `approvals/.lock`, an empty file created exclusively, and removes it when it is done,
also after an error. If it finds the file, `bt approve` stops with exit code 8 and `another approval is in progress (.lock exists in the approvals
folder); if no other bt approve is running, delete that file and try again`, and nothing is written.

A **stale lock** remains only if a process was killed while it held the lock (a crash, a power cut, a closed terminal).
Make sure that no `bt approve` is running, then delete the file `approvals/.lock` by hand; nothing else needs repair,
because the record is replaced atomically and is either the old or the new one.

## The static check

`backtest_agent.coded.static` reads the source with `ast` and never imports or runs it. It reports **every** rule that the
source breaks, with the line and a rule name. The rules apply to the whole syntax tree, not only to the top level, because
default arguments, decorators, class bodies and comprehensions run when the module is imported.

- the source is UTF-8, without byte order mark, at most 64 KiB, and parses (a source too deep for the parser is a finding,
  not a crash);
- no character of the categories Cc, Cf, Zl or Zp, comments and strings included, except a line break and a tab (the CR of
  a CRLF is removed first; a lone CR is refused); at most 10 such findings are listed, then `... and N more`;
- imports only from `numpy`, `pandas`, `math`, `typing`, `pydantic` and `__future__`, and from
  `backtest_agent.spec.signals` only `SignalParams`, `register_signal`, `close_frame`, `carry_forward` and
  `per_symbol_signal`; no relative and no star imports;
- no use of `eval`, `exec`, `compile`, `open`, `__import__`, `getattr`, `setattr`, `delattr`, `globals`, `locals`, `vars`,
  `input`, `breakpoint`, `help`, `exit`, `quit`; no name or attribute that starts and ends with two underscores;
- no attribute that evaluates a string (`eval`, `query`), reads (`read_*`, `load`, `loadtxt`, `genfromtxt`, `fromfile`,
  `fromregex`, `DataSource`, `parse_file`, `parse_raw`), writes (every `to_*` except `to_numpy`, `to_list`, `to_frame`, `to_dict`, `to_series`,
  `to_datetime`, `to_numeric`, `to_timedelta`, `to_period`, `to_timestamp`, `to_pydatetime`; `save*`, `tofile`, `memmap`, `open_memmap`),
  reaches the file system or C code (`io`, `ctypeslib`, `f2py`, `distutils`) or changes process-wide state at import time
  (`set_option`, `reset_option`, `option_context`, `options`, `seed`, `seterr`, `seterrcall`, `set_printoptions`);
- no `global`, `nonlocal` or async code; the top level holds a docstring, imports, classes, functions and assignments of
  literal constants only;
- exactly one use of `register_signal`, as the decorator `@register_signal("<id>", ...)` of a top-level function, with the
  id of the file as its first argument.

**It is a tripwire, not a sandbox.** It catches the obvious and the accidental. A determined author can get around it, and
the known gaps are listed in [ADR 0018](adr/0018-coded-signals-and-approval-gate.md). The defences that count are the person
who reads the whole code before approving it and the gate that runs only approved bytes.

## The contract and `warmup_rows()`

Every signal, coded or not, passes the contract of [strategy-spec.md](strategy-spec.md) on every call
([ADR 0017](adr/0017-signal-runtime-contract.md)). `warmup_rows()` of the params model must return a **Python `int` of at
least 0**: `True`, `1.5`, `2.0`, a string and a NumPy integer such as `np.int64(2)` are refused with
`warmup_rows must be an integer of at least 0, got ...`, because a value that prints like an integer but is not one is a
surprise the contract avoids. Write `return int(self.window)` if the value comes from NumPy.

The checks that need the code to run live in `backtest_agent.coded.contract` (purity, determinism, the output rules and an
honest `warmup_rows` on frames with different calendars, never on real data). That a forward peek is caught there is a
convenience on synthetic frames; the look-ahead test on real data is Phase 15.

## The gate: `resolve_coded`

`resolve_coded(spec, *, approvals_dir, strategies_dir)` in `backtest_agent.coded.loader` is the only place that executes a
coded signal. It turns a spec with a `coded` block into a spec that can run, or raises. The order of its steps matters,
because every refusal happens **before any file is compiled**:

1. the spec has a `coded` block and its id passes the id rules;
2. the idea `{signal_id, brief}` is approved in `approvals/<id>.json`;
3. the hash of the code to run is chosen (the table below) and must be listed for that idea;
4. the archive `approvals/code/<sha256>.py` is read once, its hash is compared with the name and the static check runs
   again on those bytes;
5. only then are those bytes compiled and executed, in a module object that is **not** put in `sys.modules`, with
   `dont_inherit=True`; exactly one new registry entry with the id must appear, and it is marked with the hash;
6. the params are validated by the params model of the code and written into the spec with their defaults, and the check
   before a run (below) is made with them. The returned spec has `coded.code_sha256` set.

### Which hash runs

`strategies_dir` says where the editable code is. It is a parameter, not inferred from the spec.

| `strategies_dir` | The file `<id>.py` | The spec pins a hash | Result |
|---|---|---|---|
| `None` (stored mode, `bt report`) | never read | required | the pin must be listed for the idea, else a `RecordError` (a record that cannot be reproduced, exit code 5); no pin: `RecordError` |
| a folder (run mode: `bt run`, `bt validate --data`, `bt data fetch`) | exists | no | its hash must be listed for the idea; that archived hash runs. Otherwise `code not approved: the file has sha <first 8 hex>` (`NotApprovedError`, exit code 8) |
| a folder | exists | yes, equal to the file's | the same, the hash must be listed |
| a folder | exists | yes, different | `the spec pins <8 hex> but strategies/signals/<id>.py has sha <8 hex>` (exit code 8), **even if the file's hash is approved** |
| a folder | does not exist | yes | the pin is used; it must be listed |
| a folder | does not exist | no | the latest approved hash of the idea; none: `code not approved: no code is approved for the idea` |

The working file is only hashed, never executed. It is `stat`-ed first and must be a regular file of at most 128 KiB (twice
the limit of approved code, because a file saved with CRLF is longer than its LF form); a longer file is refused
(`... is larger than the limit; approved code is at most 64 KiB`) before it is opened, and at most one byte more than the
limit is read. A file that is not a regular file is `... cannot be read (not a regular file)`. Because the file decides in
run mode, **editing the file and running without a new approval is refused**, and going back to an older approved version
makes that version run. A stored run (`bt report`) never reads the folder: it runs the pinned hash from the archive, whatever
was done to the working file since.

### What happens in the registry

- An id that is registered by something other than the gate (a built-in, a fixture) is a `GateError`.
- The same hash that is already loaded in this process is reused without executing again; a different hash replaces the
  gate's own entry. The registered `Signal` carries `sha256`, and `SignalSpec.resolve_signal()` (used by `params_model()`,
  `warmup_rows` and the engine) only gives a spec the signal that carries the hash the spec pins; a spec resolved for one
  version therefore refuses to run after another version was loaded, until it is resolved again. Resolve a spec just before
  you run it.
- **Whenever `resolve_coded` raises, the registry is exactly what it was before the call.** Code that was loaded and then
  failed a later step (the params, the check of the defaults, the check before a run) is unloaded again, so a retry executes
  it once more.
- Whatever else the code changed in the process stays changed; only the registry is restored (known gap 3 of the ADR).

### What the code may do when it is loaded and called

`KeyboardInterrupt` and `GeneratorExit` always pass through. Anything else the code raises, **`SystemExit` included**, is an
error of the gate where the gate calls the code: a `GateError` when the code is loaded or when its params model is used at the
gate, a `SignalContractError` (`<id> on the <frame> frame: <Type>: <text>`) in the contract and honesty checks, a failed case in
`cases.yaml`, and a `SignalContractError` from `Signal.generate` (the params model, the function and `warmup_rows`) for a signal
that carries a hash. Built-in signals and fixtures are not guarded.

So the claim is: a `SystemExit` (or any other error) that the code raises while it is loaded, checked or called through
`Signal.generate` is a contract error. It is **not** a claim that a coded signal cannot end the process. The guard does not
cover code that behaves differently after the gate has passed it (state), reached through `params.warmup_rows()` in
`warmup_window` and through a params model that the engine uses directly (known gap 5 of the ADR).

### Errors and the exit codes

The gate, `resolve_coded`, raises `NotApprovedError` (something has to be approved: exit code **8**), `RecordError` (the
approvals folder cannot supply what the spec needs or was changed, for example an archive that is missing or does not match its
hash: exit code **5**, in the stored mode of `bt report` and in the run mode too), `StaticCheckError` and `SignalContractError`
(the code is not acceptable: exit code **9**), `SpecError` (the params do not fit the params model of the code: exit code 3) and
`GateError` (the code did not load or its params model is not usable: exit code **9**, "code rejected"). It raises nothing
else, and it does not run `cases.yaml`: `bt signal check` does, and it also raises `CasesError`, which `bt` maps to exit
code 9 like `StaticCheckError` and `SignalContractError` (no other command raises it). `bt approve` adds `ApprovalError` (exit code 8: another approval is running, the idea is not approved),
`ApprovalFormatError` (a record that is not valid: exit code 5) and `ConfirmationError` (`--sha` missing or wrong: exit
code 8). `SignalContractError` is exit code 9 for every signal, a built-in one too (it was code 1 before Phase 10). The
mapping is in `cli/errors.py` and the table is in [cli.md](cli.md), "Exit codes".

## The params model of a coded signal

The spec stores the params with their defaults, every run validates them again, and the journal serializes them as JSON.
So the params model of the code must follow these rules, and the gate refuses it with a `GateError` that names the field
if it does not:

- every field, and every default, is a number, text, true or false, or a **list** of those: no `None` default (use a number
  that means "off" instead), no tuple (use a list), no dict, no nested list, no NaN or infinity;
- the model must accept its own defaults (a default that breaks its own `Field(..., le=1)` is refused);
- a validator of the model may raise `ValueError` for a bad value; anything else it raises is also turned into a
  `GateError`, but it is a bug of the code;
- `warmup_rows()` returns a Python `int` of at least 0 (see above).

## The check before a run

After the params are validated, the gate runs the contract check of `backtest_agent.coded.contract` on **synthetic frames
of 120 rows** (never on real data): the function does not modify its input, gives the same answer twice, obeys the output
rules and the zero rows on frames with different calendars (a plain frame, holidays, a late start, an early end, a short
history, a single symbol), and its declared `warmup_rows` is honest, which also catches a forward peek on these frames.
Every error names the signal and the frame, for example `rsi_pullback on the calendars frame: ...`.

There is **no sampling and no time rule**: every check runs on every row, so the same code and params give the same answer
on every machine. Measured on the development machine, the check makes 250 calls of the function and takes 0.27 to 0.8 s (0.27 to 0.37 s for signals like the built-in ones, 0.75 to 0.79 s for a heavy one with seven rolling statistics); `bt signal check` uses
frames of 300 rows (610 calls, 0.9 to 1.9 s) and runs the examples of `cases.yaml`. A signal that needs more than about 10 ms
per call exceeds three seconds in the check on its own; nothing can interrupt a function that is running (known gap 4). The
same code with the same params is checked once per process (the cache key is the pair hash and params); a failed check is
not remembered. This is not the look-ahead test on real data (Phase 15).

## `cases.yaml`: the examples of a coded signal

The signal coder writes its tests as **data**, because a pytest file would import agent code in every test run. A case gives
closing prices of a few symbols and the exposure the signal must produce on every row; `null` means that the symbol does not
trade that day. Rows are consecutive Monday-to-Friday days from 2024-01-02; open, high and low equal the close and the volume
is 1000. A worked example for a signal that is 1.0 on a day when the close is above the previous close of the symbol:

```yaml
signal: up_day
cases:
  - name: rises, falls and rises
    prices:
      AAA: [10, 11, 10, 12]
      BBB: [null, 20, 21, 19]
    expected:
      AAA: [0, 1, 0, 1]
      BBB: [0, 0, 1, 0]
```

Calculated by hand: AAA row 0 is its first trading row (warm-up of one row: 0); 11 is above 10 (1); 10 is not above 11 (0);
12 is above 10 (1). BBB does not trade on row 0; row 1 is its first trading row (0); 21 is above 20 (1); 19 is not above 21
(0). `tests/test_coded_docs.py` parses this block with `parse_cases` and runs it with such a signal.

- `signal` (optional) must be the id of the file; `params` (optional) are the params of every case, with the rules of the
  params of a coded spec; `cases` holds 1 to 50 cases with a `name`, `prices` and `expected` of 1 to 10 symbols and 1 to 400
  rows each, the same number of rows everywhere, prices above 0 and finite, exposures between 0 and 1.
- The file is read with the safe YAML loader: no aliases, no key given twice, no hidden characters (the categories of the
  rule above), at most 256 KiB, at most 20 brackets open at once, counted over the whole text, quotes and comments included, so 21 unclosed brackets anywhere are refused, and it must be a regular file. They are counted before the parser sees the text, because PyYAML needs quadratic time for a long run of opening brackets.
- The examples run through `Signal.generate`, so the output rules and the zero rows hold in them too. A difference is
  listed with the case, the symbol, the row, the date and both values (at most ten, then `... and N more`); a case in which
  the code raises is a failed case; two values are equal within 1e-9.
- The examples are run by `bt signal check`, not by a run.

## Checking a candidate: `bt signal check`

`bt signal check SPEC` ([cli.md](cli.md), "`bt signal check SPEC`") is the check of a candidate **before** it is approved: the
static check, the contract check on frames of 300 rows and the examples of `strategies/signals/<id>.cases.yaml`. It reads the
working file as bytes (the hash it prints is the hash `bt approve` will print), runs the static check, reads and validates the
examples as data, writes one consent line to stderr and only then executes the file, checks the contract and runs the examples.
It writes nothing, approves nothing and does not read `approvals/`, so a candidate can be checked before its idea is approved;
the natural order is write, check, `bt approve --idea`, `bt approve --code`. It is the only command that runs `cases.yaml`
(`CasesError`, exit code 9, is raised only there), and the only module that may call `load_candidate`, which executes a file
nobody approved; a source-tree test checks both.

**Known gap 6: it executes code that nobody approved.** The file runs in the process of the command, with the permissions of
whoever runs it and no time or memory limit; the static check is a tripwire, not a sandbox; and only the registry of signals is
put back afterwards (known gaps 1 to 4 apply in full). Running the command is the consent, and the line on stderr says so before
anything is executed: `bt: executing strategies/signals/<id>.py (sha <8 hex>, NOT approved) in this process, with your
permissions and no time or memory limit; the static check is a tripwire, not a sandbox`. There is no `--yes` and no prompt: an
agent with a shell could pass a flag as easily, and a prompt would break the tested `main(argv, ...)` contract.

**In process, not in a subprocess.** The gate loads in the process of the command too, and a subprocess needs a design of its own (the
frames, params and examples cross a pipe; a time limit and a memory limit that work on Windows). **Not built:** running the candidate in a
subprocess with a wall-clock limit and a memory limit. An agent that runs the command runs its own code with its own permissions; the only
limit of an agent run is the timeout of its own tool; whether agents may run it unattended is decided in the agents part (pull request 4)
and stated in `docs/agents.md`. The signal coder may run `bt signal check` only in the default permission mode; the hook refuses it
otherwise (enforced). The hook cannot see whether an agent runs in the background; whether Claude Code shows the ask prompt to a person
for a background agent in the default mode was not tested. The ask rule is a second layer. The strategy architect may not run it at all
([agents.md](agents.md), "May an agent run `bt signal check`?").

## What `bt validate` says

`bt validate` reads a spec without importing anything. For a spec with a `coded` block it prints a `Signal:` line after
`Family:`, from the approval record alone (`approvals/<id>.json`): it reads neither the working file nor the archive and
loads no code. The warm-up needs the code, so it is `Warm-up:    n/a (coded signal, not loaded)`. The line is one of
`Signal:     coded, idea not approved` (no record, or another brief), `Signal:     coded, idea approved,
code not approved` (a spec that pins a hash needs that hash approved; without a pin the latest approved code counts), or
`Signal:     coded, idea and code approved (sha <8 hex>)`, and the exit code is 0 in all three states (a record that is not valid
is exit code 5). Because the line is the record's, a working file edited after the approval still shows `approved`; `bt run`
refuses that file, because the commands that run code check its hash. With `--data`, and in `bt data fetch`, the spec passes
the gate first, since the window of the data needs the warm-up: exit code 8 before the approval, the real warm-up after it.

An unresolved spec used outside the gate, from Python, still raises `UnknownSignalError` with the message
`the coded signal 'x' is not resolved; it has to pass the approval gate first`; no command shows it any more.

## Not built yet

- Running a candidate of `bt signal check` in a subprocess with a wall-clock limit and a memory limit.

Everything else in this document exists and is tested. A coded signal is checked with `bt signal check`, approved with
`bt approve`, run with `bt run` and reproduced with `bt report`.
