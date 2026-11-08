# ⏪ Hermes Time-Machine

**Run Hermes terminal commands in a restricted Docker workspace, record content-addressed file checkpoints, and rewind selected tracked files from a native Hermes Desktop pane.**

> Status: **contest MVP / integration candidate**. Local core tested; Hermes runtime validation and Desktop end-to-end testing still required. This does **not** rewind the model's live conversation, Git history, external side effects, or arbitrary system state.

## What really runs

| Surface | Implementation |
| --- | --- |
| Agent execution | `tool_execution` middleware intercepts the Hermes `terminal` tool and runs its `command` through Docker. Other tools remain native. |
| Agent memory | Plugin-owned SQLite notes plus `pre_llm_call` context injection; not a replacement for the built-in memory provider. |
| Desktop | Native `panes` contribution; plugin-scoped authenticated REST API for checkpoints, diffs, and confirmed recovery. |
| Recovery | SHA-256 content-addressed snapshots with conflict detection and a pre-restore backup. |

## Requirements

- Recent Hermes Agent build supporting `ctx.register_middleware`, dashboard plugin APIs, and Desktop Plugin SDK.
- Docker CLI + running Docker daemon, with official `python:3.12-alpine` image already pulled (`docker pull python:3.12-alpine`).
- A **dedicated, disposable** workspace directory, not a home folder, shared mount, or working directory holding credentials.
- Python 3.10+ on host. The backend uses FastAPI/Pydantic already supplied by Hermes's dashboard runtime.

## Install

```sh
# Unzip/clone the repo, then install using your Hermes version's plugin install command:
hermes plugins install file:///absolute/path/to/hermes-time-machine

# Create an isolated sample workspace and export the path before starting Hermes:
mkdir -p "$HOME/time-machine-demo"
export HERMES_TIMEMACHINE_WORKSPACE="$HOME/time-machine-demo"
docker pull python:3.12-alpine
hermes plugins enable hermes-time-machine
hermes plugins doctor /absolute/path/to/hermes-time-machine
hermes plugins validate /absolute/path/to/hermes-time-machine --install-deps
```

On Desktop, enable the **Time-Machine** half in Capabilities → Plugins. Restart the Hermes gateway after enabling its Python backend so `/api/plugins/hermes-time-machine/status` mounts. Set `HERMES_TIMEMACHINE_WORKSPACE` in the **gateway service environment**, not only in an unrelated shell.

## Demonstration

```sh
python -m unittest discover -s tests -v
python demo/demo.py
```

After installing, ask Hermes to run `pwd; printf 'def add(a,b): return a-b\n' > calculator.py` via `terminal`. The call should run inside `/workspace` in Docker, and the timeline pane should show **before** and **after** checkpoints. Select the earlier checkpoint, preview changed file paths, and click Restore twice to approve a revert. The protection status must read **Docker ready** before any protected terminal commands.

## Threat model and limitations

- **Not a general-purpose secure sandbox.** The Docker container runs with network disabled, no added capabilities, a read-only container root, memory/CPU/pid limits, and a bind mount of the single configured workspace. Docker daemon access itself is privileged; never expose it to untrusted users.
- **Only `terminal` commands** are intercepted; file editing tools, browser tools, other plugins, network API calls, database mutations, and direct native process actions can still change things outside the protected workspace. Hermes host approval mechanisms continue to run before the middleware. This plugin is *not* a global deny-all policy for other tools.
- **Not truly copy-on-write.** Docker commands write to the real dedicated workspace. Snapshots enable recovery of tracked regular files; commands could also alter symlinks, permissions, empty folders, excluded folders (`.git`, `node_modules`, `.hermes`, etc.), external mounts, or other untracked resources. Do not rely on restoration for these changes.
- Snapshot limits: max 8 MiB per file, 128 MiB total for tracked regular files. Excluded directories and symlinks are not snapshotted. Unsupported workspaces are rejected before running commands.
- The `time_machine_note` tool saves unencrypted text in per-profile SQLite and `pre_llm_call` may inject it into model context for the matching session. **Do not store secrets** in notes. File contents are persisted locally, unencrypted, in `plugin-data/hermes-time-machine/objects/`. Make sure the workspace has no secrets.
- Restore requires explicit confirmation, a current workspace fingerprint, and integrity-checked snapshot objects; another process altering files during the restore window could still race it. No crash-consistent cross-filesystem transaction is claimed. A backup checkpoint is created first.
- SQLite files and snapshots can grow indefinitely; delete the plugin's data folder manually after exporting anything needed.
- On Docker daemon failure the tool returns a visible `TIME MACHINE BLOCKED` message, **not a fallback to the host**. Exceptions inside the middleware are caught to avoid Hermes's normally fail-open middleware behavior.
- Network: no application telemetry and no third-party API usage. Docker image pull is a separately initiated network operation; Docker daemon manages images.
- Cross-platform: POSIX (Linux/macOS) is primary; Windows Docker bind-mount/user semantics need testing.

## Architecture

```text
Hermes tool request → Hermes guardrails/approvals → tool_execution middleware
                                       │
                              terminal only?
                         ┌─────────────┴─────────────┐
                         no                          yes
                    native tool             snapshot before
                                                   ↓
                                      Docker /workspace command
                                                   ↓
                                            snapshot after
                                                   ↓
                                      SQLite event + tool result
                                                   ↓
                     Hermes Desktop pane ← authenticated scoped REST
                                                   ↓
                                 Preview → confirm → backup → restore
```

## Disclosures for catalog PR

- Reads and can overwrite/delete *tracked regular files* inside the explicitly configured workspace during confirmed restoration.
- Spawns Docker CLI commands (no host-shell fallback), with controlled container resources and workspace bind mount.
- Saves copies of tracked workspace files, event metadata, and optional human notes locally; no telemetry.
- Does not replace Hermes's official memory provider or guarantee whole-session reversion.

MIT licensed. See [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) for the 90-second recording outline.