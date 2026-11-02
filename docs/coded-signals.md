# Coded signals

A **coded signal** is a signal function that an agent writes after the maintainer approved the idea behind it. The engine
never trusts it: the code is hashed, archived, checked statically and checked against the signal contract before it runs,
and nothing is imported before it was approved. The project is educational and not investment advice. The decisions are in
[ADR 0018](adr/0018-coded-signals-and-approval-gate.md); the signal contract itself is in
[strategy-spec.md](strategy-spec.md); the counting of trials is in [journal.md](journal.md).

> **Public.** Everything described here is tracked in git, so it is public in this repository: `strategies/signals/*.py`,
> their `cases.yaml`, every file in `approvals/` (records and archived code) and the briefs inside the specs. Never put
> anything private in a brief or in code.

This document describes what exists after Phase 10 part 2a: the `coded` block of the spec, the hashes, the approval
records and the static check. The loader (the gate that runs approved code), the commands `bt approve` and
`bt signal check` and the agents come in later parts of the phase; where this document mentions them it says so.

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
| `strategies/signals/<id>.py` | the candidate code, editable | the signal coder agent |
| `strategies/signals/<id>.cases.yaml` | hand-calculated examples as data (a later part) | the signal coder agent |
| `approvals/<id>.json` | the append-only approval history of one signal id | the approval commands |
| `approvals/code/<sha256>.py` | the approved code, LF line ends; the file name is its hash | the approval commands |
| `approvals/.lock` | exists only while an approval runs; git-ignored | the approval commands |

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
also after an error. If it finds the file, it stops with `another approval is in progress (.lock exists in the approvals
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

## Not built yet in this part

The loader that compiles and runs approved bytes (the only place in `src/` that may do so), the `cases.yaml` runner, the
commands `bt approve` and `bt signal check`, the line `Signal: coded, idea not approved` of `bt validate`, and the agents.
They are described in [ADR 0018](adr/0018-coded-signals-and-approval-gate.md) so that the rules are fixed before they are
built. Until the loader exists, nothing in the project executes a coded signal.
