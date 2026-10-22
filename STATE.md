# STATE

Updated: 2026-10-22T13:03:17Z (E001 accepted; health cycles clean)

## Objective

Run a bounded, evidence-based loop that improves this system's own engineering workflow
and tool capabilities, using official OpenCode clients and a genuinely free model, with
checkpointed state and rollback. V2.1.2 is installed; V1.19.3 is the active free-tier
adapter because V2's hosted free tier currently returns 403.

## Environment

- Android/Termux, aarch64, 8 cores, 3.7 GB RAM (~0.9 GB available at bootstrap), 34 GB
  free disk. Persistent local filesystem.
- Codespaces is the best theoretical environment but has 0 h remaining this month, so
  the 5-hour quota guard forbids starting it. Kaggle is ephemeral/GPU-only;
  GitHub Actions is ephemeral CI. Local Termux is the strongest **available** environment.
- Official V2 executes through the musl artifact plus an explicit server, but its hosted
  free tier returns 403 for this account/network. The official V1 client is the active
  free-model adapter. See `config/install.json`, `config/model.json`, and `REPORT.md`.

## Installed

- OpenCode V2 `2.1.2`, package `@opencode/cli-linux-arm64-musl@2.1.2`, binary SHA-256
  `fa3b15239254262bbb8dc6016ed39ab8b181e8e2ab7db4be70bcb0fbe6877d28`.
- Launcher: `~/.local/opencode-v2/bin/opencode2` (isolated libs and state).
- Existing V1 `1.19.3` untouched.

## Model

- Default: `opencode/deepseek-v4.1-flash-free`.
- Cost: $0 input/output/cache (OpenCode free model, limited-time availability).
- Auth: existing OpenCode Console API key in `~/.local/share/opencode/auth.json`, read
  at runtime; never copied into this workspace. No billing or paid provider is used.
- V2 smoke: exact response `V2_MODEL_OK` in 9 s at install time. Later V2 inference
  returns `403 FreeTierError`; the official V1.19.3 client with the same model succeeds.
- Active adapter: `tools/modelrun` (V1 `opencode run --pure --format json --agent propose`).
  One call per run, 180 s cap, proposal-only, no tool authority.

## Baseline

Captured 2026-10-22 in `benchmarks/results/baseline.json`: 20/20 frozen queries correct,
warm median batch 524.162 ms, cold 343.228 ms, 28/28 tests passing, 12/12 tool probes
passing, state restore and stale-lock recovery 100%.

## Current status

- E001 accepted and measured: warm 45.759 ms (0.0873x), cold 45.939 ms (0.0876x),
  correctness 20/20, tests 28/28.
- Active backend: `tools/search.py` (indexed candidate). Rollback:
  `rollback/E001-search-index-search.py.bak`.
- Checkpoint after: `checkpoints/ckpt-20261022T125422Z-post-E001-search-index.json`;
  final after docs: `checkpoints/ckpt-20261022T130317Z-final.json` (verified).
- Model: one call, 46.36 s, $0, valid no-op proposal recorded; not executed.
- Runs 2 and 3 were no-model health cycles; run_count=3, no pending/failed experiments,
  clean worktree.
- Local commits: `52d7c85`, `6270eb6`, `bc93e11`, `7fd2188`.
- Next task: review the proposal and gate E002; no further experiment ran.

## Known limitations

- No kernel/container isolation: `unshare` is not permitted. Confinement is code-level.
- Free model availability is limited-time and rate-limited by the provider. V2.1.2's
  hosted free tier currently returns 403 for this account/network; V1 is the active
  free adapter.
- `opencode run --standalone` and service self-spawn fail on Termux (loader exec path);
  `tools/oc2run` is an explicit `serve` + `--server` diagnostic, not the active adapter.
- Termux `git` aborts at startup under a 768 MiB `RLIMIT_AS`; the cap is now 3 GiB.
- Phone RAM is small; only one model call/server at a time, and the runner stops if
  available memory falls below 250 MB.
- A process interrupted with SIGKILL can leave a stale lock; the next run detects and
  clears it only after confirming the PID is dead.

## Deliberately not done

- No public repository, push, deployment, paid key, or background daemon.
- No modification of the existing V1 configuration or session database.
- No V2 inference while its free tier rejects this client; no paid fallback was used.
- No claim of general intelligence or unsupervised self-improvement.

## 2026-10-22T12:54:22Z — E E001-search-index accepted

- warm ratio 0.0873 (limit 0.75)
- cold ratio 0.0876 (limit 1.25)
- correctness 1.0
- tests True
- checkpoint checkpoints/ckpt-20261022T125422Z-post-E001-search-index.json
- checkpoint verified True


## 2026-10-22T12:55:09Z — Free-model proposal recorded

- ok: True
- elapsed_ms: 46360.225
- path: proposals/2026-10-22T125509Z-model.json
- The proposal was recorded only; it was not executed.


## 2026-10-22T13:49:46Z — E E002-scan-fast accepted

- warm ratio 0.0466 (limit 0.75)
- cold ratio 0.0477 (limit 1.25)
- correctness 1.0
- tests True
- checkpoint checkpoints/ckpt-20261022T134946Z-post-E002-scan-fast.json
- checkpoint verified True

