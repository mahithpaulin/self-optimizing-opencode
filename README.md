# Self-Optimizing OpenCode

An action-driven, evidence-based optimization loop for the engineering workflow around
the official OpenCode V2 CLI. It is local-first, uses only a zero-cost model, runs in
bounded cycles, checkpoints every accepted change, and never grants itself unrestricted
authority over the host.

This is not a plan. `./soo run` executes inspect -> identify -> hypothesize -> implement
-> test -> evaluate -> persist -> repeat, and writes measurable results.

## Quick start

```bash
cd ~/projects/self-optimizing-opencode

# Health check (no model call)
python3 -m tools.runner --max-iterations 0 --no-model

# One bounded optimization cycle (deterministic candidate; no model required)
python3 -m tools.runner --max-iterations 1 --no-model

# One cycle with one proposal-only free-model call
python3 -m tools.runner --max-iterations 1 --model-call

# Full tests
python3 -m unittest discover -s tests -v
```

`STOP` in this directory stops the runner at the next stage boundary. Every run writes a
report under `logs/`, appends to `STATE.md`, and records history in
`experiments/history.jsonl`.

## What is installed

- Official OpenCode V2 CLI `2.1.2` (npm artifact
  `@opencode/cli-linux-arm64-musl@2.1.2`), installed in isolation at
  `~/.local/opencode-v2/2.1.2` and launched as `opencode2`.
- Existing OpenCode V1 `1.19.3` is untouched and still works as `opencode`.
- Default model: `opencode/deepseek-v4.1-flash-free` (zero input/output price; requires
  the existing OpenCode Console API login; see `config/model.json`).
- Workspace: this directory, persistent on the phone.

The official installer's `opencode run --standalone` path cannot run on Termux as-is:
the process executable is the musl loader, so the CLI's self-spawn resolves to
`ld-musl ... serve` and fails. `tools/oc2run` starts an official `opencode serve`
process explicitly and connects the official client to it with `--server`. No fork is
used as the CLI.

## Layout

```
config/        install, model, permission and budget records
tools/         executable tools, security layer, runner
benchmarks/    fixed corpus, frozen expected results, baseline/after metrics
experiments/   proposals, candidates, diffs, measured outcomes
tests/         automated tests (protected from the worker)
proposals/     raw model proposals
rollback/      last-known-good copies for accepted file changes
checkpoints/   tar.gz snapshots + SHA-256 manifests
logs/          bootstrap evidence and per-run reports
STATE.md       current truth; state.json is the machine-readable mirror
```

## Safety boundary (actual, not aspirational)

The worker is a same-UID Python process, so this is not a container. It enforces:

- all file reads/writes through `tools/security.py`, confined to this workspace by
  realpath; secret-name and protected-path denial;
- an executable allowlist with argument validation, no shell, sanitized environment,
  CPU/file-size/open-file rlimits, a 30 s timeout, and process-group cleanup;
- no repository push, deployment, publishing, messaging, purchase, background service,
  or outbound git operation; git is local-only;
- V2 is used as a **proposal-only** model behind an agent whose permissions deny every
  tool, so it cannot act on the host;
- worker subprocesses get black-holed proxy variables and no API key; the only intended
  network egress is the model adapter.

`unshare -n` and `unshare -m` both return `Operation not permitted` on this Android
device, and no container/root is available. Network isolation is therefore enforced by
code path and environment, not by a kernel namespace. This limitation is tested and
stated rather than hidden.

See `ARCHITECTURE.md` and `config/permissions.json`.
