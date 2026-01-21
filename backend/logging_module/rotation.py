"""
Log file rotation and compression.

Handles daily log rotation, compression of old files, and cleanup based on retention policy.
"""

import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from loguru import logger

from logging_module.models import LogRotationConfig


class LogRotator:
    """
    Manages log file rotation and cleanup.

    Features:
    - Daily rotation at midnight UTC
    - Compression of old log files (.gz)
    - Automatic cleanup after retention period
    - Size-based rotation (optional)
    """

    def __init__(self, config: LogRotationConfig):
        """
        Initialize log rotator.

        Args:
            config: Rotation configuration
        """
        self.config = config
        self.log_dir = Path(config.log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def should_rotate(self, log_file: Path) -> bool:
        """
        Check if log file should be rotated.

        Args:
            log_file: Path to log file

        Returns:
            True if rotation needed
        """
        if not log_file.exists():
            return False

        # Check size-based rotation
        if self.config.max_bytes > 0:
            if log_file.stat().st_size >= self.config.max_bytes:
                logger.info(f"Log file {log_file} exceeds size limit, rotating")
                return True

        # Check daily rotation
        if self.config.rotate_daily:
            # Get file modification time
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            now = datetime.now()

            # Rotate if file is from a different day
            if mtime.date() < now.date():
                logger.info(f"Log file {log_file} is from previous day, rotating")
                return True

        return False

    def rotate_log(self, log_file: Path) -> Optional[Path]:
        """
        Rotate log file by renaming with timestamp.

        Args:
            log_file: Path to current log file

        Returns:
            Path to rotated file, or None if rotation failed
        """
        if not log_file.exists():
            return None

        # Generate rotated filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rotated_name = f"{log_file.stem}_{timestamp}{log_file.suffix}"
        rotated_path = log_file.parent / rotated_name

        try:
            # Rename current log file
            shutil.move(str(log_file), str(rotated_path))
            logger.info(f"Rotated log file: {log_file} -> {rotated_path}")

            # Compress if enabled
            if self.config.compress_old:
                compressed_path = self.compress_log(rotated_path)
                if compressed_path:
                    return compressed_path

            return rotated_path

        except Exception as exc:
            logger.error(f"Failed to rotate log file {log_file}: {exc}")
            return None

    def compress_log(self, log_file: Path) -> Optional[Path]:
        """
        Compress log file with gzip.

        Args:
            log_file: Path to log file to compress

        Returns:
            Path to compressed file (.gz), or None if failed
        """
        if not log_file.exists():
            return None

        compressed_path = log_file.with_suffix(log_file.suffix + ".gz")

        try:
            with open(log_file, "rb") as f_in:
                with gzip.open(compressed_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # Remove original file after successful compression
            log_file.unlink()

            logger.info(f"Compressed log file: {log_file} -> {compressed_path}")
            return compressed_path

        except Exception as exc:
            logger.error(f"Failed to compress log file {log_file}: {exc}")
            return None

    def cleanup_old_logs(self) -> int:
        """
        Delete log files older than retention period.

        Returns:
            Number of files deleted
        """
        cutoff_date = datetime.now() - timedelta(days=self.config.retention_days)
        deleted_count = 0

        # Find all log files (including compressed)
        log_pattern = "*.log*"
        for log_file in self.log_dir.glob(log_pattern):
            if log_file.is_file():
                # Check file modification time
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)

                if mtime < cutoff_date:
                    try:
                        log_file.unlink()
                        logger.info(
                            f"Deleted old log file: {log_file} "
                            f"(age: {(datetime.now() - mtime).days} days)"
                        )
                        deleted_count += 1
                    except Exception as exc:
                        logger.error(f"Failed to delete old log file {log_file}: {exc}")

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old log files")

        return deleted_count

    def get_log_files(self) -> List[Path]:
        """
        Get list of all log files (sorted by modification time).

        Returns:
            List of log file paths
        """
        log_files = list(self.log_dir.glob("*.log*"))
        log_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return log_files

    def get_disk_usage(self) -> int:
        """
        Calculate total disk usage of log files.

        Returns:
            Total size in bytes
        """
        total_size = 0
        for log_file in self.get_log_files():
            if log_file.is_file():
                total_size += log_file.stat().st_size
        return total_size

    def rotate_if_needed(self, log_file: Path) -> bool:
        """
        Check and rotate log file if needed.

        Args:
            log_file: Path to log file

        Returns:
            True if rotation was performed
        """
        if self.should_rotate(log_file):
            rotated = self.rotate_log(log_file)
            return rotated is not None
        return False

    def maintenance(self, current_log_file: Path) -> None:
        """
        Perform maintenance tasks.

        Args:
            current_log_file: Path to current active log file
        """
        # Rotate current log if needed
        self.rotate_if_needed(current_log_file)

        # Cleanup old logs
        self.cleanup_old_logs()

        # Log disk usage
        usage_mb = self.get_disk_usage() / (1024 * 1024)
        logger.info(f"Log disk usage: {usage_mb:.2f} MB")


def setup_rotation_schedule(rotator: LogRotator, log_file: Path) -> None:
    """
    Setup automatic rotation schedule (for use with scheduler).

    Args:
        rotator: LogRotator instance
        log_file: Path to log file to rotate
    """
    import schedule

    # Daily rotation at midnight UTC
    schedule.every().day.at("00:00").do(rotator.rotate_log, log_file)

    # Daily cleanup
    schedule.every().day.at("00:05").do(rotator.cleanup_old_logs)

    logger.info("Log rotation schedule configured")


def decompress_log(compressed_file: Path) -> Optional[Path]:
    """
    Decompress gzipped log file.

    Args:
        compressed_file: Path to .gz file

    Returns:
        Path to decompressed file, or None if failed
    """
    if not compressed_file.suffix == ".gz":
        return None

    decompressed_path = compressed_file.with_suffix("")

    try:
        with gzip.open(compressed_file, "rb") as f_in:
            with open(decompressed_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        logger.info(f"Decompressed log file: {compressed_file} -> {decompressed_path}")
        return decompressed_path

    except Exception as exc:
        logger.error(f"Failed to decompress log file {compressed_file}: {exc}")
        return None
