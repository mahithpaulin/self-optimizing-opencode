# ROADMAP

Ordered, measurable work. One experiment per cycle; each must be reversible.

## E001 — indexed search backend (pending)

**Weakness:** the search tool shells out to `grep` for every query, paying process,
argument, and output-parsing overhead on every call; inspections issue many queries.

**Hypothesis:** an in-process index with regex matching returns byte-identical results
and reduces warm batch latency by at least 25% on the frozen corpus, without a material
cold-start penalty (<= 25% over baseline).

**Accept only if:** dev + held-out correctness 100%; all tests pass; no protected file
changed; warm median <= 0.75x baseline; cold batch <= 1.25x baseline median.

**Rollback:** `rollback/E001-search.py.bak` restores the previous active backend.

## E002 — failure classifier (backlog, not implemented)

Classify test/tool failures into `permission`, `timeout`, `syntax`, `assertion`,
`environment`, `model`, `unknown`, and verify against a labeled fixture set. Acceptance:
>= 90% on held-out labeled failures and no change to existing tests. Not part of this
run unless E001 completes and budget remains.

## E003 — checkpoint restore drill (backlog)

Restore a checkpoint into `rollback/restore-*`, run the suite there, and record the
verified restore rate. Never overwrite the live workspace automatically.

## Rules

- Benchmarks and evaluation rules are frozen during a run. The worker cannot edit
  `tests/`, `benchmarks/heldout.json`, `benchmarks/expected.json`, or
  `config/permissions.json`.
- Development queries (`benchmarks/tasks_dev.json`) and held-out queries
  (`benchmarks/tasks_heldout.json`) are separate; acceptance reports both.
- A generated file or a zero exit code is not evidence. Only the frozen correctness
  hashes, full suite result, and measured latency decide acceptance.
- Each accepted change gets a checkpoint and a local git commit. No remote push.
