# Claude Code Project Instructions - RFM

> **Purpose:** Guide all Claude Code sessions to maintain project standards
> **Status:** Active - Read this file at the start of every session
> **Last Updated:** 2026-02-09

---

## File Documentation System

This project uses **three separate documentation files** at the root level:

### 1. **TODO.md** - Active Work Items
- Current bugs and issues
- Future work items
- Critical rules and checklists (condensed version)
- **Update when:** Adding new tasks, marking items complete, discovering new issues
- **Keep it:** Clean and minimal - only active items

### 2. **DONE.md** - Completed Work Log
- Chronological history of all completed features and fixes
- Implementation details and file changes
- Bug fixes and their root causes
- **Update when:** Completing significant work, fixing bugs, implementing features
- **Format:** Add new entries at the top with date header

### 3. **LESSONS_LEARNED.md** - Critical Patterns & Anti-Patterns
- Detailed failure modes and their solutions
- Correct vs. wrong patterns with code examples
- Why certain bugs are "invisible" (silent failures)
- Prevention checklists
- **Update when:** Discovering a new class of bug, finding invisible failure modes, establishing new patterns
- **Keep it:** Detailed with examples - this is the knowledge base

---

## Mandatory Actions for Every Session

### When Starting Work:
1. **Read TODO.md** - Understand current active items and critical rules
2. **Scan LESSONS_LEARNED.md** - Review patterns relevant to your current work
3. **Follow KISS and DRY principles:**
   - **KISS (Keep It Simple, Stupid):** Only add what's requested or clearly necessary
   - **DRY (Don't Repeat Yourself):** Extract common patterns, use shared utilities

### During Development:
1. **Follow the 13 Critical Rules** in TODO.md (they exist to prevent recurring bugs)
2. **Check LESSONS_LEARNED.md** before implementing WebSockets, Windows integrations, or authentication
3. **Test edge cases** mentioned in lessons learned (e.g., nested paths, expired tokens)

### When Completing Work:
1. **Update TODO.md:**
   - Mark completed items
   - Remove or update stale entries
   - Add new issues discovered

2. **Update DONE.md:**
   - Add entry at the top with date header
   - Include: issue description, root cause, fix summary, files modified
   - Keep it concise but complete

3. **Update LESSONS_LEARNED.md (if applicable):**
   - Add new pattern if you discovered an "invisible" bug
   - Include: problem description, root cause, correct pattern, wrong pattern, prevention checklist, why it's invisible
   - Use code examples

---

## Code Quality Standards

### KISS (Keep It Simple, Stupid)
- ❌ Don't add features not requested
- ❌ Don't refactor code you're not changing
- ❌ Don't add error handling for impossible scenarios
- ❌ Don't create abstractions for one-time operations
- ✅ Only implement what's requested
- ✅ Keep solutions minimal and focused
- ✅ Trust internal code and framework guarantees

### DRY (Don't Repeat Yourself)
- ❌ Don't copy-paste code blocks
- ❌ Don't duplicate logic across modules
- ❌ Don't hardcode values in multiple places
- ✅ Extract common patterns to shared functions
- ✅ Use configuration files for repeated values
- ✅ Create utilities for repeated operations

---

## Critical Bug Prevention

**Before ANY change involving:**
- **Database schemas:** Check TODO.md Rule 1 (Schema ↔ Endpoint ↔ Model sync)
- **WebSocket endpoints:** Read LESSONS_LEARNED.md WebSocket patterns
- **Windows client:** Read LESSONS_LEARNED.md Windows integration pattern
- **Environment variables:** Check TODO.md Rule 7 (naming conventions)
- **Frontend-backend communication:** Check TODO.md Rule 9 (format alignment)
- **Python async:** Check TODO.md Rule 6 (`[async]` extras)

**After EVERY significant change:**
- Update relevant documentation file (TODO/DONE/LESSONS_LEARNED)
- Run basic smoke tests
- Check for similar code that might need the same fix

---

## Documentation Update Templates

### TODO.md Entry:
```markdown
### Known Issues
- [ ] **Brief description:** Detailed explanation of the issue
```

### DONE.md Entry:
```markdown
## YYYY-MM-DD - Feature/Fix Name
- **Issue:** Description of what was wrong
- **Root cause:** Why it happened
- **Fix:** What was changed
- **Impact:** Result of the fix
- **Files modified:** List of changed files
```

### LESSONS_LEARNED.md Entry:
```markdown
## Pattern Name

**Problem:** What goes wrong

**Root Cause:** Why it happens

**Correct Pattern:**
\`\`\`language
// Good code example
\`\`\`

**Wrong Pattern:**
\`\`\`language
// Bad code example
\`\`\`

**Prevention Checklist:**
- Step 1
- Step 2

**Why it's invisible:** Explanation of silent failure mode
```

---

## Quick Reference: Common Patterns

### When adding a new database column:
1. Update `models.py`
2. Update `schemas.py` (request AND response)
3. Update endpoint to include field in ORM object creation
4. Update migration (or merge into `001_initial_schema.py` if pre-production)

### When adding a WebSocket endpoint:
1. Manually parse query parameters from `websocket.scope`
2. Call `await websocket.accept()` BEFORE any other operations
3. Update ALL frontend clients (grep for WebSocket connections)
4. Update documentation

### When adding a config option:
1. Use `ENABLE_*` prefix for boolean toggles
2. Add to `_sync_env_config_to_db()` in `app.py`
3. Seed in migration
4. Read from DB at runtime (NOT from env)

### When adding a user-facing setting:
1. Check HTML form values
2. Verify Pydantic pattern accepts ALL form values
3. Check model default matches a valid form value
4. Check migration default
5. Check endpoint reset-to-defaults code
6. Test with browser DevTools Network tab

---

## Emergency: How to Fix Common Issues

### "My change isn't being saved to the database"
→ Check TODO.md Rule 1 - probably missing field in schema or endpoint

### "WebSocket keeps returning 400"
→ Read LESSONS_LEARNED.md WebSocket patterns - likely accept/close ordering or query parameter issue

### "Environment variable is being ignored"
→ Check TODO.md Rule 7 - probably naming convention mismatch

### "Frontend can't save my new setting"
→ Check TODO.md Rule 9 - probably Pydantic pattern mismatch

### "Token refresh isn't working"
→ Read LESSONS_LEARNED.md Windows client pattern - check field mapping

---

## Remember

- **These files exist to prevent wasted time** on recurring bugs
- **Update them diligently** - future Claude sessions depend on them
- **KISS and DRY are not optional** - they're project standards
- **Read before you code** - the lessons were learned the hard way

---

> **This file is read by every Claude Code session**
> **Keep it updated and concise**
> **Your future self (and other Claude sessions) will thank you**
