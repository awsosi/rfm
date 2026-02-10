# TODO - RFM (Remote File Manager)

> **Project:** File operation management system with microservices architecture
> **Status:** Active Development
> **Last Updated:** 2026-02-09

---

## CRITICAL RULES (Read Before Every Change)

1. **Schema ↔ Endpoint ↔ Model must stay in sync.** Pydantic silently strips unknown fields. Checklist: `models.py` column → `schemas.py` request schema → endpoint constructor → response schema.

2. **Never mark a bug "likely fixed" without code review.** Read the actual code end-to-end. "Likely" means "still broken until proven otherwise."

3. **Migrations are consolidated.** Single `001_initial_schema.py`. Merge schema changes into it during pre-production.

4. **Every client field must appear in serialization payload.** Missing fields silently default to `None`. Diff client JSON against Pydantic schema field-by-field.

5. **Single source of truth: DB at runtime, env on startup.** Env vars sync INTO DB via `_sync_env_config_to_db()`. Runtime reads ONLY from DB.

6. **Python async extras: always install `[async]`.** e.g., `elasticsearch[async]`, not bare `elasticsearch`. Missing extras cause silent runtime failures.

7. **Env var naming convention: `ENABLE_*` prefix.** If inherited name differs, add `validation_alias=AliasChoices(...)` to accept both.

8. **Frontend-backend format alignment.** HTML form values must match Pydantic validation patterns exactly. Test with DevTools Network tab.

9. **WebSocket/API endpoint paths must match everywhere.** Backend, all frontend clients, and docs must use same path. Grep before changing.

10. **Reverse proxy: Frontend `API_BASE_URL` must point to API domain,** not webui domain.

11. **Frontend config injection: ALL entry points,** not just `index.html`. Users access pages directly.

12. **Keep It Simple, Stupid (KISS).** Avoid over-engineering. Only add what's requested or clearly necessary.

13. **Don't Repeat Yourself (DRY).** Extract common patterns. Use shared functions/utilities instead of duplicating code.

> **See LESSONS_LEARNED.md for detailed patterns and examples.**

---

## ACTIVE BUGS

None currently.

---

## ACTIVE TODO ITEMS

### Known Issues
- [x] **Remote syslog delivery not working:** Fixed — see DONE.md 2026-02-10 entry.

### Future Work (Windows Client)
- [ ] Device authorization page localization (currently English-only, installer has Polish)
- [ ] Add additional languages beyond English and Polish (optional)

### Future Work (General)
- [ ] Consider migrating to a component framework (React/Vue) — long-term

---

> **Completed work:** See DONE.md
> **Lessons learned:** See LESSONS_LEARNED.md
