# 0018: Coded signals and the approval gate

- **Status:** Accepted. Built in parts: the `coded` block of the spec, the static check, the approval records, the contract
  check, the loader (the gate), the `cases.yaml` format, the check before a run, `bt approve` and the resolving commands
  (`bt run`, `bt validate`, `bt data fetch`, `bt report` with a coded spec) and, in Phase 10 part 3b, `bt signal check` with
  `load_candidate` (see the addendum at the end) are delivered; the agents are not built yet. `CasesError` is exit code 9 and
  only `bt signal check` raises it. The rules below are fixed so that the later parts build to them.

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

### Rules for the loader (built in part 2b)

- **`coded/loader.py` is the only module in `src/` that compiles or executes strategy code.** A source-tree test
  (`tests/test_coded_source_tree.py`) reads the syntax trees and checks that no other module calls the builtins `exec` or
  `compile`, uses `eval`, `__import__`, `import_module`, `importlib.util`, `runpy`, `pkgutil`, `codeop` or `types.ModuleType`,
  that `importlib.metadata` is used only in the package `__init__`, and that the registry methods that load and unload
  signals and the `sha256` marker of a `Signal` are used only by the loader and the module that defines the registry. The
  loader reads the archived bytes once, checks their hash and the static check again, and executes those bytes
  (`types.ModuleType` and `exec`, compiled with `dont_inherit=True`, no `.pyc`, the module is not put in `sys.modules`).
- **`resolve_coded(spec, *, approvals_dir: Path | str, strategies_dir: Path | str | None)` has an explicit folder
  parameter.** The mode is not
  inferred from the pin.
  - `None` is the stored mode (`bt report`): `strategies/signals` is never read, the spec must pin `code_sha256` (otherwise
    the record cannot be reproduced), and the pin must be listed in the matching idea entry.
  - With a folder (`bt run`): the file `<id>.py` is only hashed, never executed. It is `stat`-ed first and must be a regular
    file of at most twice the size limit (a CRLF file of approved code); at most one byte more than that is read. If it
    exists, its hash must be approved for the matching idea and exactly that archived hash runs; otherwise the run is
    refused with exit code 8, `code not approved: the file has sha <first 8 hex>`. If the spec also pins a hash that differs
    from the file's, the run is refused with exit code 8, `the spec pins <8 hex> but strategies/signals/<id>.py has sha <8
    hex>`, even if the file's hash is approved. If the file does not exist, the pin is used (it must be listed in the
    matching idea entry, as in the stored mode), or else the latest approved hash of the matching idea.
  - Before any of that, the idea must be approved: an id without a record, or a brief that differs from every approved one,
    is refused. A refusal happens before any file is compiled.
  - The gate raises `NotApprovedError` (a person has to approve something; exit code 8), `RecordError` (the
    approvals folder cannot supply what the spec needs or was changed; exit code 5, in stored mode and in run mode),
    `StaticCheckError` and `SignalContractError` (exit code 9), `SpecError` (the params do not fit; exit code 3) and
    `GateError` (the code did not load, or its params model is not usable; exit code 9). `resolve_coded` raises nothing else except
    `KeyboardInterrupt` and `GeneratorExit`; `tests/test_coded_gate_errors.py` has one row for every documented failure and
    checks the exact class. `CasesError` is not among them: it is raised by `coded/cases.py`, which only `bt signal check`
    calls (`bt` maps it to exit code 9, like `StaticCheckError` and `SignalContractError`; it is raised by `bt signal check` and
    by no other command), and a test checks that the loader does not import it. The mapping is in `cli/errors.py` and
    tested: `SignalContractError` is exit code 9 for every signal, built-in ones too (it was code 1), and `GateError` is
    exit code 9 ("code rejected": it never means that a person has to approve something).
- **One place where a spec finds its signal.** `Signal` has a field `sha256: str | None = None` (`None` for built-ins and
  fixtures); the loader registers through the normal decorator and then marks the entry. `SignalSpec.resolve_signal()` is
  the one place where a spec finds its signal: a coded spec without `code_sha256` is "not resolved", and one whose pin is not
  the hash of the registered signal is "not loaded" (nothing registered, another version, or a signal without a hash).
  `params_model()`, `warmup_rows` and the engine (`engine/runner.py`) all call it, so no path to the function skips the
  check and the engine no longer relies on `warmup_window` having asked first. A test bypasses `warmup_window` and shows that
  the runner refuses a wrongly marked signal on its own.
- **Re-registration in one process is tracked by the hash.** The loader owns exactly the registry entries whose `sha256` is
  not `None`. An id that is registered but not by the loader (a built-in, a fixture) is a `GateError`. The same hash that is
  already loaded is reused without executing again; a different hash replaces the loader's own entry after unregistering it.
  Resolving a spec for hash B makes a spec pinned to hash A refuse to run until it is resolved again, which is the intended
  fail-closed behaviour.
- **`resolve_coded` unloads the code again whenever it raises.** The registry snapshot is taken before the load and
  restored if anything from the load to the end fails: the params, the check of the defaults, the final validation or the
  check before a run. So the registry is exactly what it was before the call, and a retry (with corrected params, or with
  a corrected file) executes the code once more instead of reusing code that was never accepted.
- **The params model of the code.** Its defaults are written into the resolved spec, as for every signal (omitting a
  default and writing it are the same variant). They must be numbers, text, true or false, or lists of those: a `None`, a
  tuple, a dict, a nested list or a NaN as default is a `GateError` that names the field, and the model must accept its own
  defaults. A validator of the code that raises something other than a `ValueError` is a `GateError`, not a raw exception.
- **What the code raises, where the gate calls it, is an error of the gate.** `KeyboardInterrupt` and `GeneratorExit` pass
  through everywhere. Every other `BaseException`, `SystemExit` included, becomes a `GateError` when the code is loaded or
  when its params model is used at the gate, a `SignalContractError` ("`<Type>: <text>`") in the contract and honesty
  checks, a failed case in `cases.yaml`, and a `SignalContractError` in `Signal.generate` (the params model, the function
  and `warmup_rows`) for a signal that carries a hash. Built-in signals and fixtures are not guarded and behave as before.
  The guard does **not** cover code that behaves differently after the gate has passed it (state), reached through
  `params.warmup_rows()` in `warmup_window` and through a params model that the engine uses directly (known gap 5). So the
  claim is not that a coded signal cannot end the process, but that a `SystemExit` (or any other error) that the code
  raises while it is loaded, checked or called through `Signal.generate` is a contract error.
- **The check before a run has no sampling and no time rule.** It runs on synthetic frames of 120 rows, never on real data,
  and makes every check on every row (purity, determinism, the output rules, the zero rows and the truncation test of an
  honest `warmup_rows`). Measured on the development machine, 250 signal calls take 0.27 to 0.8 s (0.27 to 0.37 s for signals like the built-in ones, 0.75 to 0.79 s for a heavy one with seven rolling statistics); on the 300-row frames of `bt signal
  check` 610 calls take 0.9 to 1.9 s. The budget of three seconds is therefore a property of the signal, not a switch: a
  signal slower than about 10 ms per call exceeds it on its own. A switch to sampling that depends on the clock would make
  the outcome depend on the machine, and no timer can interrupt a function that is running (known gap 4). The first draft
  of this ADR planned a deterministic sampling above the budget; the measurement showed it is not needed, and it is dropped.
  The same code with the same params is checked once per process: the cache key is the pair (hash, params), because the
  check depends on the params; a failed check is not remembered.
- **`cases.yaml`** (`coded/cases.py`): the examples of a coded signal as data, read with the safe YAML loader without
  aliases, duplicate keys or hidden characters, at most 256 KiB, 50 cases, 10 symbols and 400 rows, with at most 20 brackets open at once, counted over the whole text, quotes and comments included, so 21 unclosed brackets anywhere are refused (PyYAML needs quadratic time for a long run of opening brackets, so they are counted before the parser sees the text). The file must be a regular file. A difference, a case in which the code raises, or an invalid file is a
  `CasesError`. Only `bt signal check` runs the examples.
- **Exit codes** (defined only in `cli/errors.py`): 8 for a gate refusal, an approval error (a lock, an idea that is not
  approved) and a missing or wrong confirmation of `bt approve --code` (which requires `--sha` with the first 8 hex of the
  hash it printed); 9 for rejected code: a failed static check, a contract check (every signal), a `GateError`, and failed
  examples (`CasesError`, raised only by `bt signal check`); 5 for a record or an archive that is missing or
  changed and for a record that is not valid, as for every record that cannot be reproduced.

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
5. **State-dependent behaviour after the gate.** The gate checks the code at one moment, on synthetic frames, and guards
   the places where it calls the code. Code that behaves differently after the gate has passed it (it keeps state: a
   counter, a cache, a flag) is not covered where it is reached outside `Signal.generate`: through `params.warmup_rows()`
   in `warmup_window` and through a params model that the engine uses directly. A `SystemExit` or another error raised
   there is not turned into a contract error, and the same state can make a run differ from the check; the review of the
   code before it is approved, and the look-ahead test (Phase 15), are what remain.

6. **Executing code that nobody approved.** `bt signal check` (addendum below) runs the working file of a candidate before
   any person has read it, in the process of the command, with the permissions of whoever runs it and no time or memory
   limit. The static check refuses what it can see; it does not make the file safe to run, and the registry is the only
   thing that is put back afterwards (gaps 1 to 4 apply in full). The person who runs the command accepts this, and the
   command says so before it executes anything.

Beyond these: the approvals are not tamper-proof (a process with write access to `approvals/` can write a record, like the
journal), the check is not a sandbox (the person who reads the code before approving it is the defence), and the look-ahead
test on real data is Phase 15.

## Consequences

- The loader is the only code that executes a coded signal, and it only executes archived bytes whose idea and hash a
  person approved; a source-tree test checks that no other module can.
- Params can vary inside an approved idea without a new approval; every variant is journaled and counted.
- `bt report` reproduces a coded run from the archive, whatever was done to the working file since.
- Approved code and approvals are public; a brief or a signal must not hold anything private.
- Existing code changed behaviour for this part: `Signal.generate` refuses a `warmup_rows` that is not a Python `int` of at
  least 0 and guards the call of a signal that carries a hash; `SignalSpec.params_model()` looks the signal up through
  `resolve_signal()`; `engine/runner.py` does the same (two lines, the engine behaves as before for every spec without a
  `coded` block); `tests/signal_contract.py` is a re-export of the package module (it keeps raising `AssertionError`); one
  line of `tests/test_journal_failures.py` writes a byte order mark as an escape (same value).
- See [coded-signals.md](../coded-signals.md) for the files, the hashes with their bytes, the lock and the rules in full.

## Addendum (Phase 10 part 3b): checking a candidate before it is approved

The rules above settle how approved code is loaded. They did not settle `bt signal check`, which has to run a file that no
person approved yet: the static check, the contract check on frames of 300 rows and the examples of `cases.yaml`, so that a
person knows what they are about to approve. These rules are added. No rule above changes; only the sentences that said
that the command is not built were corrected.

- **`load_candidate(spec, source)` in `coded/loader.py` is the second, and last, way to execute strategy code.** It is a
  context manager that yields a `Candidate` (the registered signal, marked with the hash of the LF form of the file; the
  params of the spec validated by its params model; the hash). It runs the static check again, then executes the bytes through
  the same `_execute` as the gate, so the loader still holds exactly one `exec`, one `compile` and one `ModuleType`. When the
  `with` block ends, however it ends, the registry is exactly what it was; an entry of the gate for the same id is set aside
  and put back, and an id registered by something other than the gate is a `GateError`. It never writes to `approvals/`,
  never touches the cache of the check before a run and never puts a module in `sys.modules`. The code is executed even if the
  gate already loaded the same hash: the point is to run what is in the file now.
- **Only `cli/signal_check.py` may use `load_candidate`**, and it is also the only module that imports `coded/cases.py`. The
  source-tree test (`tests/test_coded_source_tree.py`) reads the syntax trees for the name, an attribute, an import of it and the
  string `"load_candidate"` outside `coded/loader.py` and `cli/signal_check.py`; the importer test of `coded/cases.py` names
  exactly that one module. A name computed at run time is not seen.
- **Nothing is executed until everything that is only data has passed.** The command reads the file as bytes, runs the static
  check and reads and validates `<id>.cases.yaml` (a missing or invalid file is a `CasesError`) before it executes anything. Then it
  prints the consent line, then it loads, then it checks the contract, then it runs the examples.
- **The command is the consent, and it says what is being accepted.** Before the first byte of the candidate is executed, stderr
  gets one line: `bt: executing strategies/signals/<id>.py (sha <8 hex>, NOT approved) in this process, with your permissions
  and no time or memory limit; the static check is a tripwire, not a sandbox`. It is not written when nothing is executed (a
  failed static check, a file that cannot be read, a spec without a coded block, a missing or invalid `cases.yaml`), and it is
  written once when the candidate is executed, also when the checks fail afterwards. There is no `--yes` and no prompt: an agent
  with a shell could pass a flag as easily, and a prompt would break the tested `main(argv, ...)` contract.
- **Process, not subprocess.** The gate also loads in the process of the command, and a subprocess needs a design of its own
  (the frames, params and examples cross a pipe; a time limit and a memory limit that work on Windows). So gaps 3 and 4 stay
  open for this command, and gap 6 is the price. **Hardening that is NOT built:** running the candidate in a subprocess with a
  wall-clock limit and a memory limit. An agent that runs the command runs its own code with its own permissions, as it could with
  Python; the only limit of an agent run is the timeout of its own tool. Whether agents may run the command unattended is decided
  in the agents part (pull request 4), which must state it in `docs/agents.md`. It is stated there and decided in
  [ADR 0019](0019-agents-and-their-guardrails.md).
- **A candidate can be checked before its idea is approved, and the command does not read `approvals/`.** The order is write,
  check, approve the idea, approve the code (`bt approve --code` refuses an unapproved idea). A damaged record cannot fail a
  check, and "writes nothing, approves nothing" holds by construction.
- **Exit codes.** `CasesError` is raised for the first time and is exit code 9, as are a failed static check, a failed contract
  check and a `GateError`; a file that is missing, not a regular file or too large is 9 here (the `NotApprovedError` of
  `read_working_file` becomes a `GateError` with the same text: nothing is waiting for an approval).
