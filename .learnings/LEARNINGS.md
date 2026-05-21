# Learnings

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | knowledge_gap | best_practice

---

## [LRN-20260521-001] best_practice

**Logged**: 2026-05-21T19:39:30+08:00
**Priority**: medium
**Status**: pending
**Area**: backend

### Summary
Pandas-based adaptive thresholds should sanitize numeric series before computing standard deviation or percentile statistics.

### Details
The `oil_gold_link` factor exposed a `RuntimeWarning: invalid value encountered in subtract` through `series.pct_change().std()`. Cleaning non-numeric and infinite values upstream makes adaptive thresholding and z-score calculations safer across factors.

### Suggested Action
Apply numeric coercion, inf filtering, and NaN dropping inside shared statistical helpers in `BaseFactor`.

### Metadata
- Source: conversation
- Related Files: factors/base.py, factors/cross/oil_gold_link.py
- Tags: pandas, robustness, statistics
- Pattern-Key: harden.input_validation
- Recurrence-Count: 1
- First-Seen: 2026-05-21
- Last-Seen: 2026-05-21

---
