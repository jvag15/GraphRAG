#!/usr/bin/env bash
# daily_cycle.sh
# Nightly maintenance loop orchestrator.
# Manages ingestion or system validation cycles.

# Absolute paths
POOL_DIR="/opt/graphrag/data/ingestion_pool/unprocessed_pool"
PROJECT_DIR="/home/graphrag/graphrag_engine"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
COORDINATOR_SCRIPT="$PROJECT_DIR/ingestion_mouth/batch_coordinator.py"
VALIDATION_SCRIPT="$PROJECT_DIR/validate_system.py"
LOG_FILE="$PROJECT_DIR/logs/daily_cycle.log"

# Create logs directory if missing
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - [DAILY CYCLE] - $1" >> "$LOG_FILE"
    echo "$1"
}

log "Nightly cycle check started."

# Count PDF files in the unprocessed pool (case-insensitive)
pdf_count=$(find "$POOL_DIR" -maxdepth 1 -iname "*.pdf" | wc -l)

if [ "$pdf_count" -gt 0 ]; then
    log "Found $pdf_count files in unprocessed pool. Executing ingestion pipeline..."
    
    # Export mandatory execution environment variables for VRAM and memory manager
    export LD_PRELOAD=/usr/lib/libjemalloc.so
    export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
    
    # Run the batch coordinator script
    "$PYTHON_BIN" "$COORDINATOR_SCRIPT" >> "$LOG_FILE" 2>&1
    exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log "Ingestion completed successfully with exit code 0."
        
        # Clear the staging folder as requested on successful completion
        STAGING_DIR="/opt/graphrag/data/ingestion_pool/staging"
        log "Clearing staging folder: $STAGING_DIR"
        find "$STAGING_DIR" -mindepth 1 -delete >> "$LOG_FILE" 2>&1
        
        # Append completion event to an ingestion log
        INGESTION_SUMMARY_LOG="$PROJECT_DIR/logs/ingestion_summary.log"
        echo "$(date '+%Y-%m-%d %H:%M:%S') - SUCCESS: Ingested $pdf_count files successfully." >> "$INGESTION_SUMMARY_LOG"
    else
        log "ERROR: Ingestion pipeline failed with exit code $exit_code."
        exit $exit_code
    fi
else
    log "No files found in unprocessed pool. Executing validate_system.py sweep..."
    
    # Execute validation script
    "$PYTHON_BIN" "$VALIDATION_SCRIPT" >> "$LOG_FILE" 2>&1
    exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log "System validation sweep completed successfully."
    else
        log "ERROR: System validation sweep failed with exit code $exit_code."
        exit $exit_code
    fi
fi

log "Nightly cycle completed."
exit 0
