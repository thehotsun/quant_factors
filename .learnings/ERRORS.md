# Errors

Command failures and integration errors.

---

## [ERR-20260521-001] subagent streamTo incompatibility

**Logged**: 2026-05-21T19:26:00+08:00
**Priority**: medium

`sessions_spawn` rejects `streamTo` when `runtime="subagent"`; it is only supported for `runtime="acp"`. Use the subagent runtime without streamTo, or switch to ACP for streamed child sessions.

---

## [ERR-20260521-002] wrong environment token target

**Logged**: 2026-05-21T19:39:00+08:00
**Priority**: high
**Status**: mitigated
**Area**: config

### Summary
When configuring service environment variables, an unrelated API key was initially placed into `TUSHARE_TOKEN` before being corrected.

### Error
Wrong secret mapped to the right environment variable name. The service was not restarted with the bad value.

### Context
Systemd drop-in for `quant-factors.service` was created while continuing the quant factor hardening task.

### Suggested Fix
Always verify secret purpose before writing environment drop-ins; prefer redacted status output and avoid restart until validation passes.

### Metadata
- Reproducible: no
- Related Files: ~/.config/systemd/user/quant-factors.service.d/10-env.conf

---

## [ERR-20260521-003] repeated subagent streamTo incompatibility

**Logged**: 2026-05-21T20:06:00+08:00
**Priority**: medium
**Status**: pending
**Area**: tooling

### Summary
Repeated the known mistake of passing `streamTo` to `sessions_spawn` with `runtime="subagent"`.

### Error
```
streamTo is only supported for runtime=acp; got runtime=subagent
```

### Context
Attempted to spawn a read-only financial audit subagent for `quant_factors`.

### Suggested Fix
For subagent runtime, omit `streamTo`; only use `streamTo` with `runtime="acp"`.

### Metadata
- Reproducible: yes
- Related Files: .learnings/ERRORS.md
- See Also: ERR-20260521-001

---

## [ERR-20260521-002] shell quoting failure in grep pattern

**Logged**: 2026-05-21T20:06:00+08:00
**Command Type**: local shell / grep
**Severity**: low

**What happened**: A sensitive-string grep command failed with `unexpected EOF while looking for matching '"'` because the regex mixed single quotes inside a single-quoted shell string.

**Resolution**: For complex regex containing both single and double quotes, use `python`/ripgrep with a here-doc or simplify quoting instead of embedding nested quote patterns directly in one shell string.

## [ERR-20260521-001] wrong Python environment for project dependency

**Logged**: 2026-05-21T21:10:00+08:00
**Priority**: low

Tried to inspect AKShare with system `python3`, which failed because project dependencies live in `./quantenv`. Use `./quantenv/bin/python` for quant_factors dependency checks and scripts. No secrets involved.

## [ERR-20260521-002] importing server internals by stale variable name

**Logged**: 2026-05-21T21:11:00+08:00
**Priority**: low

A diagnostic script tried `from server import FACTOR_PARAMS`, but current server internals use underscored names. Prefer loading config directly for diagnostics to avoid server import side effects.

## [ERR-20260521-003] composite analyze route mismatch in regression script

**Logged**: 2026-05-21T21:13:00+08:00
**Priority**: medium

A naive full-chain regression called `/analyze/<chain>` for every chain in `chains.yaml`; three composite chains (`energy_chain`, `metals_chain`, `macro_chain`) returned `unknown chain`. Regression scripts should respect server-supported composite routes or server should expose all configured chains consistently.

## [ERR-20260521-004] ignored generated parquet in git add

**Logged**: 2026-05-21T21:14:00+08:00
**Priority**: low

Tried to stage `data/cbot_soybean.parquet`, but data files are intentionally ignored. Do not force-add generated market data unless explicitly requested; commit the fetch/refresh code instead.

## [ERR-20260521-001] api_smoke_databus_path_mismatch

**Logged**: 2026-05-21T21:31:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests/backend

### Summary
API smoke tests failed because `DataBus` singleton was initialized with an absolute data directory, while server or factor instantiation paths still used the relative default `data`/`./data`.

### Details
During full regression, `/analyze/<chain>` returned 400 with `DataBus 已用 data_dir=... 初始化，不能切换为 data_dir=data` for most chains. The issue came from inconsistent data directory paths between server initialization and factor instantiation/testing.

### Suggested Action
Use one canonical absolute `DATA_DIR` path everywhere in the server runtime and tests to avoid DataBus singleton path conflicts. If tests need isolation, reset `DataBus` deliberately between cases.

### Metadata
- Source: conversation
- Related Files: server.py, tests/test_api_smoke.py, core/data_bus.py
- Tags: databus, tests, singleton, path-consistency

---

## [ERR-20260521-002] edit_exact_text_mismatched_file

**Logged**: 2026-05-21T22:08:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary
A multi-edit attempted to patch `core/factor_runner.py` using an exact block from `server.py`, so the edit failed before any replacement was applied.

### Context
When editing multiple files or nearby concepts, read the target file immediately before patching and keep each edit scoped to the correct file.

### Suggested Fix
Use separate edit calls per file when touching similar call sites such as `SignalLogger.log(...)` in `core/factor_runner.py` and `server.py`.

### Metadata
- Reproducible: yes
- Related Files: core/factor_runner.py, server.py

---
