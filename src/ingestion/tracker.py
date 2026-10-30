import os
import json
import hashlib
from datetime import datetime
from pathlib import Path
from src.models import Chunk


class Tracker:
    """
    SHA256-based deduplication tracker for the GraphRAG ingestion pipeline.
    Maintains state in data/ingestion_log.json.
    """
    def __init__(self, log_path: str):
        self.log_path = log_path
        self._log_data = self._load_log()

    def _load_log(self) -> dict:
        if os.path.exists(self.log_path):
            with open(self.log_path, "r", encoding="utf-8") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}

    def _save_log(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.log_path)), exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(self._log_data, f, indent=4)

    def compute_sha256(self, path: str) -> str:
        """Helper to compute SHA256 of a file."""
        sha256_hash = hashlib.sha256()
        with open(path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def is_ingested(self, path: str) -> bool:
        """Returns True only if the file's current SHA256 is logged with status == 'complete'."""
        if not os.path.exists(path):
            return False
        
        current_hash = self.compute_sha256(path)
        record = self._log_data.get(current_hash)
        
        if record and record.get("status") == "complete":
            return True
            
        return False

    def mark_stage(self, path: str, stage: str, chunk_count: int = None):
        """Update the status of a file in the log."""
        if not os.path.exists(path):
            return
            
        current_hash = self.compute_sha256(path)
        
        record = self._log_data.get(current_hash, {
            "path": os.path.abspath(path),
            "filename": os.path.basename(path),
            "ingested_at": datetime.utcnow().isoformat() + "Z",
            "chunk_count": 0,
            "status": "pending"
        })
        
        record["status"] = stage
        record["ingested_at"] = datetime.utcnow().isoformat() + "Z"
        if chunk_count is not None:
            record["chunk_count"] = chunk_count
            
        self._log_data[current_hash] = record
        self._save_log()

    def get_pending(self, ingestion_dir: str) -> list[str]:
        """
        Return paths of files in the ingestion directory that are not yet fully ingested.
        If a file's SHA256 changed, it will be returned for re-ingestion.
        """
        pending_files = []
        if not os.path.exists(ingestion_dir):
            return pending_files
            
        for root, _, files in os.walk(ingestion_dir):
            for file in files:
                file_path = os.path.join(root, file)
                
                # If a file's SHA256 is already in the log with status "complete", skip it.
                # If SHA256 changed (file was updated), it won't be found as complete, thus returning it.
                if not self.is_ingested(file_path):
                    pending_files.append(file_path)
                    
        return pending_files
