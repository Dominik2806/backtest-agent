# 0018: Coded signals and the approval gate

- **Status:** Accepted. Built in parts: the `coded` block of the spec, the static check, the approval records and the
  contract check are delivered; the loader, the commands and the agents follow. The rules below are fixed now so that the
  later parts build to them.

## Context

Phase 10 lets an agent write the one piece of Python that the project does not control, the signal function. The engine,
the data layer and the metrics stay deterministic and tested ([ADR 0002](0002-deterministic-core-llm-never-writes-engine.md)).
A coded signal is the first code that is written by an LLM and then run, so the question is when it may be loaded and what
the maintainer has seen by then. [ADR 0006](0006-signal-contract.md) already required that discovery only imports files
that an approved spec names and only after the approval gate; the roadmap put the gate in Phase 12, but the mechanism has to
exist the moment code can be loaded. Three facts shaped the design:

- A spec for a signal that is not coded yet could not be read: the spec looked the id up in the registry and validated the
  params against a params model that does not exist before the code does.
- The approval of a spec cannot vouch for code that does not exist yet, and the maintainer should be able to change params,
  universe and period inside an approved idea without a new approval (Phase 14 varies params all the time).
- A reproduction has to run the code that ran, not the file that happens to be on disk now.

## Decision

**The spec names the idea, not a file.** `signal.coded` is an optional block `{brief, code_sha256}`. A spec that has it is not
looked up in the registry when it is read, its params must be scalars or lists of scalars, and it cannot run until the gate
has resolved it (`params_model()` and `warmup_rows` raise `UnknownSignalError` for a spec without `code_sha256`, whatever the
registry holds). The block is left out of `to_dict()` when it is not used, so the variant hash of every other spec is
byte-identical. The id is a file-safe pattern, not a built-in id and not a Windows device name; the path is derived from the
id (`strategies/signals/<id>.py`) and a spec never names a path. The code is part of the variant hash through `code_sha256`,
so rewriting it is a new variant of the same family and the trial counter stays honest.

**Two approvals, in this order, both by a person.** The **idea** is `{signal_id, brief}`; its hash is the SHA-256 of the
canonical JSON, with CRLF turned into LF in the brief and nothing stripped. The **code** is the SHA-256 of the source with
CRLF turned into LF. Nothing else of the spec is part of either: params, universe, period, costs and the rest are checked
at every run by the params model and the risk flags, and a changed parameter is a new variant and a counted trial. The
human gate on a complete spec stays with Phase 12. Reasons against, accepted: the params model of the code is then the only
bound on the params, so the review of the code includes it; the brief is the only approved text, so it must state the logic,
every parameter and the history needed. Code is approved only for an approved idea and only if it passes the static check;
the printout that precedes the approval shows the whole file with line numbers and its hash.

**The approvals are an append-only history** in `approvals/<id>.json`: a list of idea entries, one per idea hash, each with
the code hashes approved for it. A changed brief adds an entry; nothing is overwritten or cleared, so an old stored run still
reproduces. Approving what is already approved is a no-op that keeps the first timestamp. The approved bytes are archived as
`approvals/code/<sha256>.py`, and **what runs is the archive, never the editable file**. An approval takes the exclusive lock
file `approvals/.lock` because it reads, changes and writes the record; a stale lock is deleted by hand. Alternatives
rejected: overwriting the record (a stored run could no longer be reproduced), a lock-free read-modify-write (two approvals
at once lose an entry, which breaks the history this file exists to keep), and keeping the approval in the spec file (the
spec changes with every parameter).

**LF.** The hash is of the LF form, and `.gitattributes` makes `approvals/**` and `strategies/signals/*.py` LF in the working
tree, because an archive file whose bytes change on checkout fails its hash. Ruff excludes both folders (`extend-exclude`),
because `ruff format` would rewrite reviewed bytes and `ruff check` would lint code that an agent wrote. Both folders are
tracked, so approved code is public in this repository; a fresh clone must be able to reproduce a logged run.

**The static check is a tripwire.** `coded/static.py` parses the source and reports every rule it breaks, across the whole
syntax tree (default arguments, decorators, class bodies and comprehensions run at import time): an import allowlist, banned
names and attributes (including `eval`, `query`, `read_*`, every `to_*` that is not on a short allowlist, `parse_file`,
`parse_raw` and the attributes that change process-wide state), names and attributes with two underscores at both ends,
characters of the Unicode categories Cc, Cf, Zl and Zp, a top level of literals, classes and functions only, and exactly one
`@register_signal("<id>")` whose id is the id of the file. The same characters are refused in a brief and in every file of
the repository. It is not a sandbox (see the gaps).

**The contract check moves into the package** (`coded/contract.py`), raising `SignalContractError`. It runs on synthetic
frames before a coded signal runs and in `bt signal check`: purity, determinism, the output rules and an honest
`warmup_rows` (a function that looks at the future differs from its truncated-history value, so a forward peek is caught on
synthetic data; the real look-ahead test is Phase 15). `Signal.generate` also refuses a `warmup_rows` that is not a Python
`int` of at least 0.

### Rules for the loader (built in the next part)

- **`coded/loader.py` is the only module in `src/` that compiles or executes strategy code.** A source-tree test checks that
  `importlib`, `exec(` and `compile(` appear nowhere else. It reads the archived bytes once, checks their hash and the static
  check again, and executes those bytes (`types.ModuleType` and `exec`, no `.pyc`, the module is not put in `sys.modules`).
- **`resolve_coded(spec, *, approvals_dir, strategies_dir: Path | None)` has an explicit folder parameter.** The mode is not
  inferred from the pin.
  - `None` is the stored mode (`bt report`): `strategies/signals` is never read, the spec must pin `code_sha256` (otherwise
    the record cannot be reproduced), and the pin must be listed in the matching idea entry.
  - With a folder (`bt run`): the file `<id>.py` is read as bytes and hashed, never executed. If it exists, its hash must be
    approved for the matching idea and exactly that archived hash runs; otherwise the run is refused with exit code 8,
    `code not approved: the file has sha <first 8 hex>`. If the spec also pins a hash that differs from the file's, the run is
    refused with exit code 8, `the spec pins <8 hex> but strategies/signals/<id>.py has sha <8 hex>`, even if the file's hash
    is approved. If the file does not exist, the pin is used, or else the latest approved hash of the matching idea.
  - Before any of that, the idea must be approved: an id without a record, or a brief that differs from every approved one,
    is refused. A refusal happens before any file is compiled.
- **The registered signal carries the hash it was loaded from.** `Signal` gets a field `sha256: str | None = None` (`None` for
  built-ins and fixtures). The loader registers through the normal decorator and then marks the entry. `params_model()` and
  `warmup_rows` of a spec with `code_sha256` require that the registered signal carries the same hash and raise
  `UnknownSignalError` ("not loaded") otherwise. `run_backtest` reaches `warmup_rows` in `warmup_window` before it asks for
  the signal, so the engine needs no change, and a test pins it with two hashes.
- **Re-registration in one process is tracked by the hash.** The loader owns exactly the registry entries whose `sha256` is
  not `None`. An id that is registered but not by the loader (a built-in, a fixture) is a `GateError`. The same hash that is
  already loaded is reused without executing again; a different hash replaces the loader's own entry after unregistering it;
  any failure restores the registry to its state before the call. Resolving a spec for hash B makes a spec pinned to hash A
  refuse to run until it is resolved again, which is the intended fail-closed behaviour.
- **The pre-run check is deterministic.** It runs on synthetic frames, never on real data. If it exceeds its budget of three
  seconds, it samples a fixed list of rows (no randomness) and the documentation states the reduced power; `bt signal check`
  always runs the full check. A hash that passed once in a process is not checked again.
- **Exit codes** (defined only in `cli/errors.py`): 8 for a gate refusal and a missing confirmation of `bt approve --code`
  (which requires `--sha` with the first 8 hex of the hash it printed), 9 for a failed static or contract check; a stored run
  whose record or archive is missing is exit code 5, as for every record that cannot be reproduced.

## Known gaps

The static check and the gate reduce risk; they do not remove it. These are known and accepted:

1. **The `str.format` introspection trick.** `"{0.__class__}".format(x)` reaches an attribute through a string that the check
   does not parse as code. An f-string is parsed and checked; a format string is not.
2. **Class bodies and default arguments may call allowed library functions at import time.** The check bans names and
   attributes, not calls to permitted functions, so a class body or a default argument can run allowed NumPy or pandas code
   when the module is executed.
3. **The loader restores the registry only, not other global state.** Whatever allowed code changes elsewhere in the process
   (a module attribute, the random state of a library) stays changed after a failed load.
4. **There is no time or memory limit.** An infinite loop or a huge allocation in the candidate code hangs or crashes the
   process. The budget of the pre-run check cannot interrupt a function that is running.

Beyond these: the approvals are not tamper-proof (a process with write access to `approvals/` can write a record, like the
journal), the check is not a sandbox (the person who reads the code before approving it is the defence), and the look-ahead
test on real data is Phase 15.

## Consequences

- Nothing in the project executes a coded signal until the loader exists, and the loader only executes archived bytes whose
  idea and hash a person approved.
- Params can vary inside an approved idea without a new approval; every variant is journaled and counted.
- `bt report` reproduces a coded run from the archive, whatever was done to the working file since.
- Approved code and approvals are public; a brief or a signal must not hold anything private.
- Three existing files changed behaviour or content for this part: `Signal.generate` refuses a `warmup_rows` that is not a
  Python `int` of at least 0; `tests/signal_contract.py` is a re-export of the package module (it keeps raising
  `AssertionError`); one line of `tests/test_journal_failures.py` writes a byte order mark as an escape (same value).
- See [coded-signals.md](../coded-signals.md) for the files, the hashes with their bytes, the lock and the rules in full.
