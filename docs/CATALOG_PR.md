# Catalog PR: Add Hermes Time-Machine

## Summary

Hermes Time-Machine adds Docker-scoped terminal execution, content-addressed checkpoints, a local note-to-context hook, and a native Hermes Desktop pane for browsing change history and restoring selected tracked files with explicit confirmation.

## Public extension surfaces

- `ctx.register_middleware('tool_execution', ...)`: intercepts only the `terminal` tool and returns an explicit error if the managed workspace or Docker is unavailable; for other tools calls `next_call`.
- `ctx.register_hook('pre_llm_call', ...)`: injects previously saved plugin-owned notes for the current session; **not** a replacement memory provider.
- `ctx.register_tool(...)` for four tools.
- `desktop/plugin.js`: contributes a pane and palette command using `@hermes/plugin-sdk`.
- `dashboard/plugin_api.py`: authenticated plugin-scoped REST endpoints.

## Safety and disclosures

- Spawns Docker CLI, with the configured workspace as a writable bind mount. Docker daemon privileges apply. Container networking is disabled; host-level Docker image acquisition is separate.
- Reads, hashes, and stores copies of workspace regular-file contents (unencrypted) within the Hermes plugin-data directory; restore overwrites/deletes changed tracked files **only after confirmation**.
- Never claims to protect excluded directories, symlinks, filesystem metadata, external services, built-in nonterminal tools, or Hermes conversation history.
- Persists plugin-owned human notes as unencrypted SQLite records and can inject them into future model turns.
- No outbound telemetry. No OAuth tokens, saved credentials, or external SaaS connections.
- `HERMES_TIMEMACHINE_WORKSPACE` environment variable is required; daemon and image must be installed by operator.

## Verification (to be completed on developer machine)

- [x] Python core unit tests pass locally.
- [x] Standalone example restores a deliberately broken file.
- [x] Desktop ESM syntax checked by Node.
- [ ] `hermes plugins doctor <path>` (Hermes CLI not available in build environment).
- [ ] `hermes plugins validate <path> --install-deps` (Hermes CLI not available in build environment).
- [ ] Docker-enabled agent integration test on a machine with Docker daemon.
- [ ] Desktop pane screenshot + live interaction recording.
- [ ] Link public standalone plugin repo at pinned 40-character commit SHA.

See README for threat model and demo instructions.