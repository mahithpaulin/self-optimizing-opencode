# ARCHITECTURE

## Execution model

`python3 -m tools.runner` is the only entry point. It owns the cycle and the budgets.
The model never gets tool authority: the V2 `propose` agent denies every tool and only
returns text. All actions are taken by deterministic Python that passes through
`tools/security.py`.

```
runner
  A inspect      tools/inspect.py -> logs/inspect-*.json
  B identify     read state, test results, tool probes, backlog
  C hypothesize  load proposal.json; optional one-shot model proposal (validated)
  D implement    compile candidate into sandbox/ (never directly active)
  E test         unittest suite + baseline benchmark + candidate benchmark
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

`tools/oc2run` starts official `opencode serve` on localhost with an ephemeral password,
waits for the port, runs official `opencode run --server ... --agent propose`, and stops
the server process group. It reads the existing authorized API key at runtime and never
writes it to disk. One call per run, 180 s cap. Output is parsed as JSON with a strict
schema; invalid or unsafe proposals are rejected and the deterministic backlog is used.
