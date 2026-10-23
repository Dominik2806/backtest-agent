# 0015: Experiment journal

- **Status:** Accepted. Phase 8 part 1 delivers the journal core; part 2 delivers `run_experiment` and the trial line of the
  report. Where this ADR touches [ADR 0014](0014-report.md) it adds to it and changes nothing in it (see the last item).

## Context

A backtest that looks good is more likely luck the more variants were tried before it. Nothing in a single report shows
that, so the project keeps a journal: every standard run is stored, listed and counted per strategy family, and the report
states the count. The layout, the schema, the definitions and the failure behaviour are in [journal.md](../journal.md).

## Decision

- **Folders are the truth, the index is a cache.** `runs/<run-id>/run.json` (plus a readable `spec.yaml`) holds a run;
  `runs/index.sqlite` only makes listing and counting fast and can be rebuilt from the folders. Alternative rejected: SQLite
  as the only store (one corrupt file would lose every run, and a run could not be inspected or copied as a folder);
  JSON only without an index (listing and counting would read every file).
- **Standard library only.** `sqlite3` for the index, `subprocess` for git, `json` for the files, `yaml` (already a
  dependency) for `spec.yaml`. Rollback-journal mode, not WAL, so there are no side files on Windows.
- **Canonical JSON, explicit scalars.** `run.json` is written with sorted keys, fixed separators and a final newline, so the
  same record is the same bytes. The cost scalars of `BacktestResult` are properties, not fields, and are written out one by
  one; `None` stays `null`. NaN and infinity raise before anything is written.
- **Family is the signal id.** It is the one stable name of "the same idea" that the spec already has. Alternative
  rejected: the strategy name (renaming would reset the counter without any effort), a hash of the signal source code
  (changes with every edit and says nothing about the idea). The limit is accepted and documented: renaming a signal id
  resets the counter, and the journal is an honesty aid, not tamper-proof.
- **Two numbers.** `run_count` counts every logged run, `trial_count` counts distinct variants. The variant hash is the
  SHA-256 of the canonical JSON of the spec without `name` and `description` (full 64 hex characters; worked example in
  [journal.md](../journal.md)). Alternatives rejected: one number that counts runs only (re-running the same spec to check
  a result would inflate the trials), a hash that includes the data hash (the same idea on revised data would look like a
  new trial), a coarser hash that ignores the period (a different period is a different test; the stored spec allows
  regrouping later, for example for the deflated Sharpe ratio of Phase 15). The variant hash is separate from the 8
  character hash of the run id, which identifies the inputs of one run.
- **All or nothing under a write lock.** `record_run` takes `BEGIN IMMEDIATE` first, so the numbers are assigned under the
  lock, then writes into a temporary folder, renames it, inserts the row and commits. Any failure rolls back and removes
  what the call created. Alternative rejected: write the folder first and number it afterwards (two processes could get the
  same number).
- **A stale index is an error, not a repair.** Under the lock `record_run` compares the folders on disk with the rows. A
  difference (an orphan folder after a crash, a deleted folder, a missing index with folders present) raises
  `JournalIndexStale`; the user calls `rebuild_index`. Alternatives rejected: starting a fresh index (resets the counters
  silently), rebuilding automatically (hides a deletion that changes the count).
- **Readers wait for a writer before they report a mismatch.** A writer is briefly between its rename and its commit, when
  a run folder exists without its row. A reader that sees a difference takes the write lock (up to 5 seconds), looks
  again, and only then raises `JournalIndexStale`; if the writer is still busy it raises `JournalBusyError`. Alternative
  rejected: no check on reads (a stale index would silently give a low trial count). The temporary folder of a write
  starts with a dot, so it never counts as a run folder.
- **Rebuild never renumbers.** `run_number` and `trial_number` come from `run.json`. The rebuild then checks per family that
  the run numbers are 1 to n without gaps and that the trial numbers follow the order of first appearance, and raises
  `JournalFormatError` otherwise. Alternative rejected: renumbering by `generated_at`, which can differ from the order of
  logging because the caller supplies the time.
- **A run id that exists raises.** The id has second resolution, so the same spec at the same second collides and
  `FileExistsError` is raised (`run_experiment` words it as "run id already exists; use a later generated_at"). Alternative
  rejected: a counter suffix, which would make the id of the journal differ from the id of the report for the same
  `generated_at`.
- **Code version without a dependency.** The git commit and a dirty flag come from `git` in the package directory and only
  count if that repository contains this package; otherwise `"unknown"`. The function is injectable so tests never depend
  on the real commit.
- **The entry point logs, the report states (part 2).** `evaluate()` and `run_backtest()` stay pure. `run_experiment`
  evaluates and logs; `write_report` takes an optional trial info, and without it prints that the count is not recorded.
  This cannot force every caller to log (a report can still be written without the journal), so it is a convention plus a
  visible "not recorded" line, not a technical guarantee. If the report fails after the journal committed, the entry
  stays: a tried run counts.
- **Moved `check_run_id`.** Both the journal and the report need the run id guard, and the report package imports the
  journal types, so the guard moved from `reporting/writer.py` to `run_id.py` and is re-exported by the writer. This
  touches ADR 0014 only in that the "neutral module" it names for the run id now also holds the guard; the run id
  format and the hash input are unchanged.
