# STATE

Updated: 2026-10-22T12:31:30Z (bootstrap)

## Objective

Run a bounded, evidence-based loop that improves this system's own engineering workflow
and tool capabilities, using only the official OpenCode V2 CLI and a genuinely free
model, with checkpointed state and rollback.

## Environment

- Android/Termux, aarch64, 8 cores, 3.7 GB RAM (~0.9 GB available at bootstrap), 34 GB
  free disk. Persistent local filesystem.
- Codespaces is the best theoretical environment but has 0 h remaining this month, so
  the 5-hour quota guard forbids starting it. Kaggle is ephemeral/GPU-only;
  GitHub Actions is ephemeral CI. Local Termux is the strongest **available** environment.
- Official V2 works through the musl artifact plus an explicit server; see
  `config/install.json` and the known limitation in `README.md`.

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
- Verified: exact response `V2_MODEL_OK` in 9 s via official V2 client/server.

## Baseline

Not captured yet. E001 compares the grep-per-query search backend with an in-process
indexed backend on a frozen 10-file corpus, 20 queries (16 dev, 4 held-out), measured
in batch; correctness is checked against frozen SHA-256 result hashes.

## Current status

- Workspace and safety layer: in progress at bootstrap.
- E001: pending.
- Next concrete task: run the full test suite, capture `benchmarks/results/baseline.json`,
  then execute E001 once and accept only if held-out correctness is 100%, no test
  regresses, and warm batch median latency improves by at least 25%.

## Known limitations

- No kernel/container isolation: `unshare` is not permitted. Confinement is code-level.
- Free model availability is limited-time and rate-limited by the provider.
- `opencode run --standalone` and service self-spawn fail on Termux (loader exec path);
  `tools/oc2run` uses explicit `serve` + `--server`.
- Phone RAM is small; only one model call/server at a time, and the runner stops if
  available memory falls below 250 MB.
- A process interrupted with SIGKILL can leave a stale lock; the next run detects and
  clears it only after confirming the PID is dead.

## Deliberately not done

- No public repository, push, deployment, paid key, or background daemon.
- No modification of the existing V1 configuration or session database.
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

