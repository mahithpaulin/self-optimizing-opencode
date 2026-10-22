# ARCHITECTURE

## Execution model

`python3 -m tools.runner` is the only entry point. It owns the cycle and the budgets.
The model never gets authority to change the workspace. The active adapter uses the
official V1 client with a `propose` agent exposing only a read-only tool (the hosted free
tier rejects zero-tool requests); write, edit, bash, network, and task tools are disabled.
The V2 `propose` agent remains configured but V2's free tier currently returns 403. All actions are taken by deterministic Python that passes through
`tools/security.py`.

```
runner
  A inspect      tools/inspect.py -> logs/inspect-*.json
  B identify     read state, test results, tool probes, backlog
  C hypothesize  load proposal.json; optional one-shot model proposal (validated)
  D implement    precheck the candidate, then promote with a backup
  E test         frozen candidate benchmark, full suite, post-promotion benchmark
  F evaluate     frozen hashes, suite result, latency ratios; accept or reject
  G persist      promote with backup, checkpoint, history, STATE.md, local git commit
  H repeat       next pending experiment until iteration/time/model budget or STOP
```

Every stage is bounded. A lock prevents concurrent runs, and the runner checks free
memory, time, iteration count, failure streak, and a `STOP` file. SIGINT/SIGTERM set a
stop flag; after the current bounded subprocess returns, state is saved and any
uncommitted candidate is discarded.

## Optimizer vs evaluator

The candidate is a standalone module under `experiments/`. It is benchmarked by
`tools/bench.py`, which is not part of the candidate and uses frozen tasks and frozen
result hashes. Promotion only happens after both the dev and held-out arms pass. Tests
and evaluation data are protected paths, so the worker cannot improve its score by
editing them. The baseline file is created once; later runs read it instead of
regenerating a favorable baseline.

## Permissions

Default deny. `config/permissions.json` is the declared policy; `tools/security.py`
implements it:

- realpath confinement to the workspace, including symlink escape rejection;
- secret-name denial (`auth.json`, `.env`, keys, tokens, `.ssh`) and outside reads;
- protected-path write denial (tests, frozen benchmarks, security module, policy);
- command allowlist (`python3 -m unittest`, local git inspection/commit, a few read-only
  utilities), no shell, validated arguments, sanitized env, rlimits, timeout;
- Termux `git` requires `RLIMIT_AS` near 3 GiB; below that the bionic linker aborts;
- network black-hole proxy env and no inherited API key for worker commands.

The actual OS is Android without user namespaces or root; `unshare` is denied and no
container exists. This is stated as a limitation, not papered over. The model adapter is
the only intended network path; it runs outside the worker command allowlist and only
returns a proposal.

## Self-modification

Candidates live in `experiments/` and are activated only by promotion. The previous
active file is saved under `rollback/`; a failed post-promotion test automatically
restores it. `tools/security.py`, `tools/search_baseline.py`, tests, frozen benchmarks,
and permission/budget config are immutable to the worker. Security-boundary changes
require explicit human approval and are not attempted here.

## State and recovery

- `state.json` (atomic writes, `.bak` previous copy) is the resumable source.
- `STATE.md` is the human log, append-only.
- `experiments/history.jsonl` is append-only evidence.
- checkpoints are tar.gz snapshots with SHA-256 manifests, excluding `.git` and old
  checkpoints to avoid recursion.
- stale locks are cleared only when the recorded PID is no longer alive.

## Model adapter

The active adapter is `tools/modelrun`, which runs the official V1.19.3 client in
`model-host/` with `--pure --format json --agent propose` and the zero-cost
`opencode/deepseek-v4.1-flash-free` model. The agent exposes only `read`; write, edit,
bash, webfetch, task, and todo tools are disabled, and the V1 config denies edit/bash/
webfetch. The adapter reads the existing authorized credential from V1's auth store and
never writes it to disk. One call per run, 180 s cap.

`tools/oc2run` is a V2 diagnostic that starts official `opencode serve` explicitly and
points `opencode run --server` at it. V2's hosted free tier returns `403 FreeTierError`
for this account/network, so this path is not used for proposals. The V2 CLI and its
`propose` agent remain installed. Output is parsed as JSON with a strict schema; invalid
or unsafe proposals are recorded and never executed automatically.
