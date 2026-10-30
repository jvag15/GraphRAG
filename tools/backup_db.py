#!/usr/bin/env python3
"""
Automated GraphRAG Database Backup Script

Compresses the SSD-based data directory and stores encrypted backups on HDD
with rolling retention policy (14 days).
"""

import os
import tarfile
import datetime
import glob
import time
from pathlib import Path

# Configuration (matches server paths)
SSD_DATA_DIR = Path("./data")
HDD_BACKUP_DIR = Path("data/ingestion_pool/backups")
RETENTION_DAYS = 14

def create_backup():
    """Create timestamped compressed backup of SSD data directory."""
    # Ensure backup directory exists
    HDD_BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Generate timestamp for unique filename
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    backup_name = f"graphrag_db_backup_{timestamp}.tar.gz"
    backup_path = HDD_BACKUP_DIR / backup_name

    # Create compressed archive
    print(f"Creating backup: {backup_path}")
    start_time = time.time()

    try:
        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(SSD_DATA_DIR, arcname=os.path.basename(SSD_DATA_DIR))

        elapsed = time.time() - start_time
        print(f"Backup completed in {elapsed:.2f} seconds")
        print(f"Backup size: {backup_path.stat().st_size / (1024*1024):.2f} MB")

        # Enforce retention policy
        enforce_retention()

    except Exception as e:
        print(f"ERROR: Backup failed: {e}")
        raise

def enforce_retention():
    """Delete backup files older than RETENTION_DAYS."""
    cutoff_time = time.time() - (RETENTION_DAYS * 86400)
    deleted_count = 0

    for backup_file in HDD_BACKUP_DIR.glob("graphrag_db_backup_*.tar.gz"):
        if backup_file.stat().st_mtime < cutoff_time:
            try:
                backup_file.unlink()
                deleted_count += 1
                print(f"Deleted old backup: {backup_file.name}")
            except Exception as e:
                print(f"ERROR: Failed to delete {backup_file}: {e}")

    if deleted_count > 0:
        print(f"Retention policy: deleted {deleted_count} backups older than {RETENTION_DAYS} days")
    else:
        print(f"Retention policy: no backups older than {RETENTION_DAYS} days found")

if __name__ == "__main__":
    create_backup()