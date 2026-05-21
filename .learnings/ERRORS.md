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
