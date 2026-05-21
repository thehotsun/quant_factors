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
