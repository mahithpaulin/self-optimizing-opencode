# REPORT — 2026-10-22

## Outcome

E001 was executed end to end and accepted. The measured warm median batch latency fell
from **524.162 ms** to **45.759 ms** (ratio **0.0873**, limit 0.75), cold batch from
**343.228 ms** to **45.939 ms** (ratio **0.0876**, limit 1.25), with **20/20** frozen
queries matching and **28/28** tests passing. The change is reversible via
`rollback/E001-search-index-search.py.bak`.

## What was built

- `tools/runner.py`: bounded Stage A–E loop, lock, budgets, precheck, promotion,
  post-promotion tests/benchmark, accept-or-rollback, checkpoints, state/history,
  local git commit, and one model call.
- `tools/security.py`: realpath workspace confinement, secret/protected-path denial,
  command allowlist, sanitized environment, rlimits, timeouts, process-group kill.
- `tools/bench.py` + `tools/freeze.py`: fixed 20-query benchmark with frozen SHA-256
  result hashes; the engine name is excluded so baseline and candidate can differ.
- `tools/checkpoint.py`: tar.gz snapshot + SHA-256 manifest + safe extraction.
- `tools/experiment.py`: proposal validation, acceptance rules, diff, backup, promote,
  rollback.
- `tools/model.py` + `tools/modelrun` + `model-host/`: one-call proposal adapter using
  the official V1 free-tier client and a read-only agent.
- `tests/`: 28 tests covering security escapes, allowlist, search equivalence,
  benchmark mismatch detection, state recovery, stale locks, checkpoint tamper/unsafe
  members, experiment promote/rollback, model parsing, and local git commit.

## Baseline and acceptance evidence

- Baseline: `benchmarks/results/baseline.json`; 20/20 correct, median 524.162 ms,
  cold 343.228 ms, 12/12 tool probes passed, state restore and stale-lock recovery
  100%, 7 capabilities with green tests.
- E001 direct candidate precheck and post-promotion benchmark both matched all frozen
  hashes. Acceptance decision:
  `warm_ratio=0.0873`, `cold_ratio=0.0876`, `correctness=1.0`, `tests_ok=true`.
- Checkpoint before: `checkpoints/ckpt-20261022T125418Z-pre-E001-search-index.json`.
- Checkpoint after: `checkpoints/ckpt-20261022T125422Z-post-E001-search-index.json`
  (verified).
- Final runner checkpoint: `checkpoints/ckpt-20261022T130317Z-final.json` (verified);
  later documentation-only edits are in the final commit.
- Local commits: `52d7c85` (measured E001), `6270eb6` (docs/adapter), `bc93e11`/
  `7fd2188` (two no-op health cycles).
- Runs 2 and 3 were `--no-model --max-experiments 0` health cycles: no experiment, no
  model call, no state corruption; run 3 confirmed a clean worktree and idempotent state.

## Model

The one proposal call succeeded in **46.36 s**, cost **$0**, and returned a valid no-op
proposal because E001 had already been adopted. It was recorded, not executed. The
official V2.1.2 CLI is installed and checksum-verified, but its hosted free tier
returns `403 FreeTierError` for this account/network. The official V1.19.3 client with
the same free model succeeds, so the active adapter uses V1. No paid model or key was
used.

## Safety and recovery

- 12/12 expected tool probes passed: outside read, symlink escape, secret-name read,
  outside write, protected write, `git push`, shell `echo`, and `python3 -c` are denied;
  `git status` and valid search succeed; invalid regex is an explicit error.
- State restore from `.bak` and stale-lock clearing both passed.
- Checkpoint tamper and unsafe tar member tests pass.
- No push, deploy, publish, message, purchase, or background service was performed.
- The runner stops on `STOP`, free memory below 250 MB, time/iteration/model budget, or
  a failure streak of 2.

## Limitations

- Same-UID process; no kernel namespace/container. `unshare` is denied on this device.
- Network confinement is code-path and environment based, not a netns.
- V2 free-tier inference is currently rejected for this account/network; V1 is the
  active free adapter. V2's explicit server is retained as a diagnostic only.
- Termux `git` requires `RLIMIT_AS` of at least ~3 GiB; the 3 GiB cap is high relative
  to the phone's 3.7 GB RAM, so the runner's free-memory guard remains important.
- One model call per run and a 180 s cap; model proposals are advisory only.
- The benchmark is deliberately small and CPU-local; it proves this change, not general
  search performance.

## Reproduce

```bash
cd ~/projects/self-optimizing-opencode
python3 -m unittest discover -s tests -v
python3 -m tools.runner --no-model --max-experiments 0
cat state.json
cat experiments/E001-search-index/result.json
cat benchmarks/results/baseline.json
```
