# ROADMAP

Ordered, measurable work. One experiment per cycle; each must be reversible.

## E001 — indexed search backend (ACCEPTED 2026-10-22)

**Weakness:** the search tool shells out to `grep` for every query, paying process,
argument, and output-parsing overhead on every call; inspections issue many queries.

**Hypothesis:** an in-process index with regex matching returns byte-identical results
and reduces warm batch latency by at least 25% on the frozen corpus, without a material
cold-start penalty (<= 25% over baseline).

**Accept only if:** dev + held-out correctness 100%; all tests pass; no protected file
changed; warm median <= 0.75x baseline; cold batch <= 1.25x baseline median.

**Result:** 20/20 queries correct; warm 45.759 ms vs 524.162 ms baseline (0.0873x);
cold 45.939 ms (0.0876x); 28/28 tests pass. Checkpoint
`checkpoints/ckpt-20261022T125422Z-post-E001-search-index.json`.

**Rollback:** `rollback/E001-search-index-search.py.bak` restores the previous active backend.

## E002 — fast scan hot path (ACCEPTED 2026-10-22)

**Weakness:** profiling showed 81% of query time in `_scan`; pathlib and splitting every
file were paid on every query. **Result:** 20/20 correct; runner 24.411 ms (direct
19.193 ms) vs 53.376 ms immediately before; 28/28 tests. Rollback:
`rollback/E002-scan-fast-search.py.bak`.

## E003 — snapshot validation (ACCEPTED 2026-10-22)

**Weakness:** the full walk repeated even when the corpus was unchanged. **Result:**
20/20 correct; runner 15.200 ms (direct 10.122 ms) vs 19.492 ms immediately before;
28/28 tests. Rollback: `rollback/E003-scan-snapshot-search.py.bak`.

## E004 — failure classifier (backlog, not implemented)

Classify test/tool failures into `permission`, `timeout`, `syntax`, `assertion`,
`environment`, `model`, `unknown`, and verify against a labeled fixture set. Acceptance:
>= 90% on held-out labeled failures and no change to existing tests. Not part of this
run unless E001 completes and budget remains.

## E005 — checkpoint restore drill (backlog)

Restore a checkpoint into `rollback/restore-*`, run the suite there, and record the
verified restore rate. Never overwrite the live workspace automatically.

## Rules

- Benchmarks and evaluation rules are frozen during a run. The worker cannot edit
  `tests/`, the corpus, `benchmarks/tasks_dev.json`, `benchmarks/tasks_heldout.json`,
  `benchmarks/expected.json`, `benchmarks/results/baseline.json`, or
  `config/permissions.json`.
- Development queries (`benchmarks/tasks_dev.json`) and held-out queries
  (`benchmarks/tasks_heldout.json`) are separate; acceptance reports both.
- A generated file or a zero exit code is not evidence. Only the frozen correctness
  hashes, full suite result, and measured latency decide acceptance.
- Each accepted change gets a checkpoint and a local git commit. The runner never
  pushes; publishing is a separate manual action.
