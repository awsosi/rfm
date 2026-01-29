# Worker Migration Guide: Pull-Based Architecture

## Overview

This guide explains how to migrate workers from the old push-based architecture to the new pull-based command queue system.

## Architecture Changes

### Before (Push-Based)
```
API → HTTP POST → Worker (requires public IP/port forwarding)
```

### After (Pull-Based)
```
API → Command Queue → Database ← Worker polls
Worker executes → Response → Database → API receives
```

## Benefits of Pull-Based Architecture

✅ **Workers behind NAT/firewalls can operate** - No need for public IPs or port forwarding
✅ **Better command tracking** - All commands stored in database with full history
✅ **Improved reliability** - Database-backed queue survives API restarts
✅ **Better debugging** - Command history visible in database
✅ **Timeout management** - Automatic handling of stuck commands

## Migration Steps

### Step 1: Update API Server

1. **Run database migration:**
   ```bash
   cd backend
   alembic upgrade head
   ```
   This creates the `worker_commands` table and adds the `CommandStatus` enum.

2. **Restart API server:**
   ```bash
   # Using docker-compose
   docker-compose restart file-manager-api

   # Or manually
   systemctl restart file-manager-api
   ```

3. **Verify API is running:**
   ```bash
   curl http://localhost:8000/health
   ```

### Step 2: Update Worker Code

The worker code has been updated in this commit. Changes include:

**Files Modified:**
- `workers/FileManagerWorker/Models/CommandRequest.cs` - Updated to match API schema
- `workers/FileManagerWorker/Models/CommandResponse.cs` - Updated to match API schema
- `workers/FileManagerWorker/CommandHandler.cs` - Updated command handlers
- `workers/FileManagerWorker/ApiClient.cs` - Minor updates for int CommandId

**Key Changes:**
1. `CommandRequest` now uses `SourcePath` and `DestPath` instead of Parameters dictionary
2. `CommandResponse` now includes `FileCount`, `TotalSizeBytes`, and structured error details
3. `CommandId` changed from `string` to `int?`
4. All command handlers updated to use new format

### Step 3: Build and Deploy Worker

1. **Build the worker:**
   ```bash
   cd workers/FileManagerWorker
   msbuild FileManagerWorker.csproj /p:Configuration=Release
   ```

   Or using Visual Studio:
   - Open solution
   - Build → Build Solution (Ctrl+Shift+B)
   - Configuration: Release

2. **Stop existing worker service:**
   ```bash
   # On Windows
   sc stop FileManagerWorker

   # Or from Services.msc
   ```

3. **Deploy new binaries:**
   ```bash
   # Backup old version
   copy C:\Program Files\FileManagerWorker C:\Program Files\FileManagerWorker.backup

   # Copy new binaries
   copy bin\Release\* "C:\Program Files\FileManagerWorker\"
   ```

4. **Start worker service:**
   ```bash
   # On Windows
   sc start FileManagerWorker

   # Or from Services.msc
   ```

### Step 4: Verify Worker Registration

1. **Check worker logs:**
   ```
   C:\Program Files\FileManagerWorker\logs\worker.log
   ```

   Look for:
   ```
   [INFO] Worker registered successfully
   [INFO] Polling for commands...
   ```

2. **Check API logs:**
   ```bash
   docker-compose logs -f file-manager-api | grep worker
   ```

   Look for:
   ```
   Worker registration: HV2012R2 (status: PENDING)
   Worker HV2012R2 polling: sent command 123
   ```

3. **Approve worker in admin panel:**
   - Login to web UI as admin
   - Navigate to Workers section
   - Find worker with status PENDING
   - Click "Approve" or set status to ACTIVE
   - Verify worker status changes to ACTIVE

### Step 5: Test End-to-End

1. **Test PUSH operation:**
   - Login to web UI
   - Navigate to Explorer
   - Select a directory in Path A
   - Click "Push >" button
   - Verify operation appears in Operation Queue
   - Check operation status changes: PENDING → IN_PROGRESS → COMPLETED
   - Verify directory copied to Path B
   - Verify directory moved to Path C (archive)

2. **Test PULL operation:**
   - Select completed PUSH operation
   - Click "< Pull" button
   - Verify operation appears in Operation Queue
   - Check operation status changes: PENDING → IN_PROGRESS → COMPLETED
   - Verify directory restored to original location
   - Verify directory removed from Path B
   - Verify archive remains in Path C

3. **Check command queue:**
   ```sql
   SELECT * FROM worker_commands ORDER BY created_at DESC LIMIT 10;
   ```

   Verify:
   - Commands created with correct status
   - Response data populated
   - File counts and sizes recorded
   - Completion times accurate

## Troubleshooting

### Worker Not Registering

**Symptoms:**
```
[ERROR] Worker registration failed: Forbidden
```

**Solution:**
- Check mTLS certificate is valid
- Verify API URL is correct in worker config
- Check network connectivity to API
- Review API logs for authentication errors

### Worker Registered but Status is PENDING

**Symptoms:**
- Worker appears in admin panel with PENDING status
- Worker cannot poll for commands (403 Forbidden)

**Solution:**
- Login as admin
- Navigate to Workers section
- Set worker status to ACTIVE
- Worker will immediately start polling

### Commands Stuck in PENDING

**Symptoms:**
```sql
SELECT * FROM worker_commands WHERE status = 'PENDING' AND created_at < now() - interval '5 minutes';
```

**Solution:**
- Check worker is online and polling
- Verify worker status is ACTIVE
- Check worker logs for errors
- Cancel stuck commands:
  ```sql
  UPDATE worker_commands SET status = 'FAILED', error_msg = 'Timeout - worker offline'
  WHERE status = 'PENDING' AND created_at < now() - interval '10 minutes';
  ```

### Operations Fail with "Worker not active"

**Symptoms:**
```
Operation failed: Worker HV2012R2 is not active (status: SUSPENDED)
```

**Solution:**
- Check worker heartbeat:
  ```sql
  SELECT name, status, last_heartbeat FROM workers;
  ```
- If heartbeat is recent but status is SUSPENDED, reactivate:
  ```sql
  UPDATE workers SET status = 'ACTIVE' WHERE name = 'HV2012R2';
  ```
- Restart worker service if heartbeat is stale

### High Database Load

**Symptoms:**
- Slow API responses
- High CPU on database server
- Large worker_commands table

**Solution:**
- Check background cleanup is running:
  ```bash
  docker-compose logs file-manager-api | grep "command queue cleanup"
  ```
- Manually clean up old commands:
  ```sql
  DELETE FROM worker_commands
  WHERE completed_at < now() - interval '7 days'
  AND status IN ('COMPLETED', 'FAILED', 'TIMEOUT');
  ```
- Consider reducing retention period in background_tasks.py

## API Endpoint Reference

### Worker Endpoints

**Registration:**
```
POST /api/workers/register
Body: {
  "name": "HV2012R2",
  "hostname": "HV2012R2",
  "public_key": "-----BEGIN PUBLIC KEY-----...",
  "path_a_prefix": "C:\\PathA",
  "path_b_prefix": "C:\\PathB",
  "version": "1.0.0"
}
```

**Command Polling:**
```
GET /api/workers/{workerId}/commands/poll?timeout=30
Response: {
  "command_id": 123,
  "command": "copy",
  "source_path": "A:/data/project",
  "dest_path": "B:/project",
  "parameters": {}
}
```

**Command Response:**
```
POST /api/workers/{workerId}/commands/{commandId}/response
Body: {
  "status": "success",
  "message": "Copy completed successfully",
  "file_count": 42,
  "total_size_bytes": 1048576
}
```

**Heartbeat:**
```
POST /api/workers/{workerId}/heartbeat
Body: {}
```

**Configuration:**
```
GET /api/workers/{workerId}/config
Response: {
  "path_a_prefix": "C:\\PathA",
  "path_b_prefix": "C:\\PathB",
  "path_c_prefix": "/mnt/pathc",
  "polling_interval_seconds": 5
}
```

## Database Schema

### worker_commands Table

```sql
CREATE TABLE worker_commands (
    id SERIAL PRIMARY KEY,
    worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
    operation_id INTEGER REFERENCES operations(id) ON DELETE CASCADE,
    command VARCHAR(50) NOT NULL,
    source_path TEXT,
    dest_path TEXT,
    params_json JSON,
    status commandstatus NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    sent_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    response_status VARCHAR(20),
    response_message TEXT,
    response_data JSON,
    error_msg TEXT,
    timeout_seconds INTEGER NOT NULL DEFAULT 300
);

CREATE INDEX ix_worker_commands_worker_status ON worker_commands(worker_id, status);
CREATE INDEX ix_worker_commands_created_at ON worker_commands(created_at);
```

### CommandStatus Enum

```sql
CREATE TYPE commandstatus AS ENUM (
    'PENDING',   -- Command created, waiting for worker
    'SENT',      -- Command retrieved by worker
    'IN_PROGRESS', -- Worker executing command
    'COMPLETED', -- Command completed successfully
    'FAILED',    -- Command failed
    'TIMEOUT'    -- Command timed out
);
```

## Monitoring

### Key Metrics to Monitor

1. **Command Queue Length:**
   ```sql
   SELECT status, COUNT(*) FROM worker_commands
   WHERE created_at > now() - interval '1 hour'
   GROUP BY status;
   ```

2. **Worker Health:**
   ```sql
   SELECT name, status, last_heartbeat,
          now() - last_heartbeat AS time_since_heartbeat
   FROM workers
   ORDER BY last_heartbeat DESC;
   ```

3. **Average Command Duration:**
   ```sql
   SELECT command,
          AVG(EXTRACT(EPOCH FROM (completed_at - sent_at))) AS avg_duration_seconds,
          COUNT(*) AS total_commands
   FROM worker_commands
   WHERE completed_at > now() - interval '24 hours'
   GROUP BY command;
   ```

4. **Failed Commands:**
   ```sql
   SELECT command, error_msg, COUNT(*) AS failures
   FROM worker_commands
   WHERE status = 'FAILED'
   AND created_at > now() - interval '24 hours'
   GROUP BY command, error_msg
   ORDER BY failures DESC;
   ```

### Grafana Dashboard Queries

If using Grafana with PostgreSQL datasource:

**Queue Depth:**
```sql
SELECT
  date_trunc('minute', created_at) AS time,
  COUNT(*) AS pending_commands
FROM worker_commands
WHERE status = 'PENDING'
AND created_at > $__timeFrom()
GROUP BY time
ORDER BY time;
```

**Worker Status:**
```sql
SELECT
  name,
  CASE
    WHEN status = 'ACTIVE' THEN 1
    ELSE 0
  END AS is_active
FROM workers;
```

## Rollback Plan

If migration fails and you need to rollback:

1. **Stop new worker:**
   ```bash
   sc stop FileManagerWorker
   ```

2. **Restore old worker binaries:**
   ```bash
   copy "C:\Program Files\FileManagerWorker.backup\*" "C:\Program Files\FileManagerWorker\"
   ```

3. **Rollback database:**
   ```bash
   cd backend
   alembic downgrade -1  # Rollback one migration
   ```

4. **Restart old worker:**
   ```bash
   sc start FileManagerWorker
   ```

5. **Verify old worker connects:**
   - Check worker logs
   - Verify operations work

**Note:** Commands created during migration will be lost in rollback. Complete in-flight operations before rolling back.

## Post-Migration Checklist

- [ ] Database migration applied successfully
- [ ] API server restarted and health check passes
- [ ] Worker binaries updated and service restarted
- [ ] Worker registered and approved (status: ACTIVE)
- [ ] Worker heartbeat updating (check last_heartbeat timestamp)
- [ ] Test PUSH operation completes successfully
- [ ] Test PULL operation completes successfully
- [ ] Verify WebSocket real-time updates working
- [ ] Check command queue cleanup running
- [ ] Monitor worker health check running
- [ ] Review logs for any errors or warnings
- [ ] Update documentation with any environment-specific changes

## Support

For issues during migration:

1. Check logs:
   - API: `docker-compose logs -f file-manager-api`
   - Worker: `C:\Program Files\FileManagerWorker\logs\worker.log`
   - Database: `docker-compose logs -f postgres`

2. Review TODO.md section "PULL-BASED WORKER COMMUNICATION" for detailed implementation notes

3. Check command queue status:
   ```sql
   SELECT * FROM worker_commands ORDER BY created_at DESC LIMIT 20;
   ```

4. Verify worker status:
   ```sql
   SELECT * FROM workers;
   ```
