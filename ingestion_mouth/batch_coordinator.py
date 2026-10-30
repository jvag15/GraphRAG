#!/usr/bin/env python3
"""
Batch Coordinator for GraphRAG Ingestion - Single Massive Unified Batch Mode

Orchestrates the ingestion by moving all unprocessed PDF documents from the pool
to the staging area, verifying the environment, and executing the ingestion pipeline
in one massive unified execution run.
"""

import os
import shutil
import subprocess
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

# Absolute paths (hardcoded per hardware profile)
POOL_DIR = Path("/mnt/parameter-archives/GraphRAG-Ingestion-DB/unprocessed_pool")
STAGING_DIR = Path("/mnt/parameter-archives/GraphRAG-Ingestion-DB/staging")
ARCHIVE_DIR = Path("/mnt/parameter-archives/GraphRAG-Ingestion-DB/archive")
QUARANTINE_DIR = Path("/mnt/parameter-archives/GraphRAG-Ingestion-DB/quarantine")
LOG_DIR = Path("/home/graphrag-automation/graphrag_engine/logs")
LOG_FILE = LOG_DIR / "batch_coordination.log"
VENV_PYTHON = Path("/home/graphrag-automation/graphrag_engine/venv/bin/python")
INGESTION_SCRIPT = Path("/home/graphrag-automation/graphrag_engine/run_ingestion.py")


def setup_logging() -> logging.Logger:
    """Configure logging to both console and file with timestamps."""
    logger = logging.getLogger("BatchCoordinator")
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    # Create formatters
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def get_pdf_files(directory: Path) -> list[Path]:
    """Return sorted list of PDF files in directory (case-insensitive)."""
    pdf_files = list(directory.glob("*.pdf")) + list(directory.glob("*.PDF"))
    return sorted(pdf_files)


def validate_directories() -> bool:
    """Ensure required directories exist; create if missing."""
    try:
        POOL_DIR.mkdir(parents=True, exist_ok=True)
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        print(f"FATAL: Failed to create required directories: {e}")
        return False


def check_and_install_requirements():
    """Check if all packages in requirements.txt are installed, install missing ones."""
    req_path = os.path.join(os.path.dirname(__file__), "..", "requirements.txt")
    if not os.path.exists(req_path):
        print(f"WARNING: requirements.txt not found at {req_path}")
        return

    print("Checking requirements.txt...")
    try:
        # Get list of required packages
        with open(req_path, 'r') as f:
            required = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        # Get list of installed packages
        result = subprocess.run([sys.executable, "-m", "pip", "list", "--format=freeze"],
                              capture_output=True, text=True, check=True)
        installed_packages = {line.split('==')[0].lower() for line in result.stdout.split('\n') if '==' in line}

        # Check each required package
        missing = []
        for package in required:
            pkg_name = package.split('==')[0].split('>=')[0].split('<=')[0].strip().lower()
            if pkg_name not in installed_packages:
                missing.append(package)

        if missing:
            print(f"Missing packages: {missing}")
            print("Installing missing packages...")
            subprocess.run([sys.executable, "-m", "pip", "install"] + missing, check=True)
            print("All requirements installed.")
        else:
            print("All requirements already installed.")
    except Exception as e:
        print(f"Warning: Could not check requirements: {e}")


def main() -> None:
    """Main batch coordination execution."""
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("GRAPHRAG UNIFIED BATCH COORDINATOR STARTED")
    logger.info(f"Pool Directory: {POOL_DIR}")
    logger.info(f"Staging Directory: {STAGING_DIR}")
    logger.info(f"Log File: {LOG_FILE}")
    logger.info("Mode: Unified Massive Batch Ingestion")
    logger.info("=" * 60)

    # Validate directory structure
    if not validate_directories():
        sys.exit(1)

    # Run check requirements exactly once on startup
    check_and_install_requirements()

    # Move all files from unprocessed pool to staging
    pdf_files = get_pdf_files(POOL_DIR)
    if pdf_files:
        logger.info(f"Moving {len(pdf_files)} PDF files from unprocessed pool to staging...")
        for f in pdf_files:
            try:
                shutil.move(str(f), str(STAGING_DIR / f.name))
            except Exception as e:
                logger.error(f"Failed to move {f.name} to staging: {e}")

    # Scan staging area
    staging_files = get_pdf_files(STAGING_DIR)
    total_files = len(staging_files)
    logger.info(f"Staging Area Scan: {total_files} PDF files ready for ingestion.")

    if total_files == 0:
        logger.info("No files to process in staging. Exiting.")
        return

    # Run single massive ingestion subprocess
    start_time = time.time()
    start_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Starting unified ingestion batch execution at {start_timestamp}")

    cmd = [
        str(VENV_PYTHON),
        str(INGESTION_SCRIPT),
        "--source",
        "staging"
    ]

    # Inherit environment and max out resource allocations (Ryzen 8 cores, 12GB VRAM RTX 3060)
    env = os.environ.copy()
    env["LLAMA_N_THREADS"] = "8"
    env["LLAMA_N_THREADS_BATCH"] = "8"
    env["LLAMA_N_CTX"] = "4096"

    try:
        # Run subprocess with real-time output streaming
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=env
        )

        # Stream output in real-time
        for line in process.stdout:
            logger.info(line.rstrip())

        return_code = process.wait()
        end_time = time.time()
        duration = end_time - start_time
        duration_str = f"{duration:.2f} seconds"

        logger.info("=" * 60)
        if return_code != 0:
            logger.error(f"UNIFIED BATCH INGESTION FAILED with exit code {return_code}")
            sys.exit(return_code)
        else:
            logger.info(f"UNIFIED BATCH INGESTION SUCCESSFUL (Duration: {duration_str})")
            
    except Exception as e:
        logger.error(f"FATAL Exception during unified ingestion: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBatch coordination interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"FATAL ERROR in batch coordinator: {e}")
        sys.exit(1)