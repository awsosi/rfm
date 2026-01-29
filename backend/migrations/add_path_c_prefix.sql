-- Migration: Add path_c_prefix column to workers table
-- Date: 2026-01-29
-- Description: Adds path_c_prefix column to support archive path (PathC) for PUSH operations

-- Add path_c_prefix column to workers table
ALTER TABLE workers ADD COLUMN IF NOT EXISTS path_c_prefix VARCHAR(500);

-- Add comment for documentation
COMMENT ON COLUMN workers.path_c_prefix IS 'Archive path prefix where PUSH operations move original directories';
