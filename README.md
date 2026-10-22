# Self-Optimizing OpenCode

An action-driven, evidence-based optimization loop for a local engineering workspace.
It runs bounded cycles: inspect -> identify -> hypothesize -> implement -> test ->
evaluate -> persist -> repeat. Every accepted change is checkpointed and committed to a
local git repository. It uses no paid provider and does not grant itself unrestricted
authority over the host.

## Current result

E001 was measured and accepted on 2026-10-22:

| Metric | grep baseline | indexed candidate | Ratio |
|---|---:|---:|---:|
| Correctness (20 frozen queries) | 20/20 | 20/20 | 1.00 |
| Warm median batch | 524.162 ms | 45.759 ms | 0.0873 |
| Cold batch | 343.228 ms | 45.939 ms | 0.0876 |
| Test suite | 28/28 | 28/28 | pass |

The accepted implementation is `tools/search.py`. The current rollback chain is
`rollback/E003-scan-snapshot-search.py.bak` (E002), `rollback/E002-scan-fast-search.py.bak`
(E001), and `rollback/E001-search-index-search.py.bak` (grep). Full evidence is in
`REPORT.md`, `campaign/rate.json`, and `experiments/*/result.json`.

### 30-minute measured campaign (2026-10-22T13:49–14:19Z)

| Point | Median batch | Change |
|---|---:|---:|
| Active at campaign start | 56.121 ms | — |
| E002 scan fast (accepted) | 24.411 ms runner / 19.193 ms direct | 64.0% vs 53.376 ms |
| E003 scan snapshot (accepted) | 15.200 ms runner / 10.122 ms direct | 48.1% vs 19.492 ms |
| Soak, 29 samples | **9.903 ms** | **82.4% below start** |
| Final sample | 7.777 ms | 86.1% below start |

Both experiments were 20/20 correct with 28/28 tests. Improvement was front-loaded:
64% in 21.7 s, then 48% in 17.0 s; the remaining 29 minutes were a stability soak.
Overall rate over the 30.013-minute window: **2.74% per minute** using the soak median
(2.87% using the single final sample). Soak p95 was 10.887 ms, with one 32.473 ms CPU
outlier; median remained ~9.9 ms. Checkpoint:
`checkpoints/ckpt-20261022T141925Z-campaign-final.json` (verified).

## Quick start

```bash
cd ~/projects/self-optimizing-opencode

# Health check: no model call, no experiments
python3 -m tools.runner --no-model --max-experiments 0

# One bounded cycle (the runner respects the one-call model budget in state)
python3 -m tools.runner

# Tests
python3 -m unittest discover -s tests -v

# A frozen benchmark in isolation
python3 -m tools.bench --module baseline --repetitions 5 --output benchmarks/results/check.json
```

`STOP` in this directory stops the runner at the next stage boundary. Runs write
`logs/runs/*.json`, append to `STATE.md` and `experiments/history.jsonl`, and update
`state.json`.

## Installation and the free-model finding

- Official OpenCode V2 CLI `2.1.2` is installed in isolation at
  `~/.local/opencode-v2/2.1.2` and launched as `opencode2`, from the official
  `@opencode/cli-linux-arm64-musl@2.1.2` artifact (SHA-512 integrity verified).
- Existing OpenCode V1 `1.19.3` is untouched and is the **active free-model adapter**.
  The same zero-cost model `opencode/deepseek-v4.1-flash-free` returns 403
  `FreeTierError` through V2.1.2 from this account/network, including with the explicit
  server or a tool-enabled agent. It succeeds through the official V1 client with the
  read-only `propose` agent. This is recorded as a negative result, not hidden.
- `tools/modelrun` is the V1 adapter. V2 remains installed and its `propose` agent is
  retained, but V2 is not used for inference until its hosted free tier accepts this
  client. No paid model or key is used.
- V2's `opencode run --standalone` cannot self-spawn on Termux because the executable
  path is the musl loader. `tools/oc2run` is the explicit-serve diagnostic; it is not
  the active adapter because the V2 free tier returns 403.

## Layout

```
config/        install, model, permission and budget records
tools/         security layer, benchmarks, runner, model adapter
model-host/    isolated V1 config with inline proposal-only agent
benchmarks/    fixed corpus, frozen expected hashes, baseline and results
campaign/      measured campaign timeline, soak samples, and rate.json
experiments/   proposals, candidates, diffs, measured outcomes, history
tests/         automated tests (protected from the worker)
proposals/     raw model responses
rollback/      last-known-good copies for promoted files
checkpoints/   tar.gz snapshots + SHA-256 manifests
logs/          bootstrap evidence, inspections, and per-run reports
REPORT.md      final evidence and limitations
STATE.md       current truth; state.json is the machine-readable mirror
```

## Safety boundary (actual, not aspirational)

The worker is a same-UID Python process, so this is not a container. It enforces:

- all file reads/writes through `tools/security.py`, confined to this workspace by
  realpath; symlink-escape, secret-name, and protected-path denial;
- an executable allowlist with argument validation, no shell, sanitized environment,
  CPU/file-size/open-file rlimits, a 30 s timeout, and process-group cleanup;
- no repository push, deployment, publishing, messaging, purchase, background service,
  or outbound git operation by the runner; publishing is a separate manual action;
- the model agent has one read-only tool because the hosted free tier rejects
  zero-tool requests; it has no write, edit, bash, network, or task tools, and its
  output is parsed as JSON but never executed automatically;
- worker subprocesses get black-holed proxy variables and no API key; the only intended
  network egress is the model adapter.

`unshare -n` and `unshare -m` both return `Operation not permitted` on this Android
device, and no container/root is available. Network isolation is therefore enforced by
code path and environment, not by a kernel namespace. This limitation is tested and
stated rather than hidden.

One Termux-specific trap is recorded in `tools/security.py`: Termux `git` aborts at
startup (`bionic/linker ... MapShadow CHECK`) under the original 768 MiB `RLIMIT_AS`.
The cap was raised to 3 GiB; the runner still refuses to start if available RAM is
below 250 MB.
