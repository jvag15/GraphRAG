#!/usr/bin/env python3
"""
Telemetry Dashboard for GraphRAG Ingestion Pipeline
Displays live metrics from ingestion_metrics.csv and unprocessed pool.
"""

import os
import csv
import time
from pathlib import Path
from datetime import datetime

# Constants
CSV_PATH = "./logs/ingestion_metrics.csv"
UNPROCESSED_POOL = Path("data/ingestion_pool/unprocessed_pool")
REFRESH_INTERVAL = 5  # seconds

def read_csv_metrics():
    """Read and parse the ingestion metrics CSV."""
    if not os.path.exists(CSV_PATH):
        return []

    metrics = []
    try:
        with open(CSV_PATH, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert numeric fields
                row['duration_in_seconds'] = float(row['duration_in_seconds'])
                row['total_tokens'] = int(row['total_tokens'])
                metrics.append(row)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return []
    return metrics

def count_unprocessed_pdfs():
    """Count PDF files in the unprocessed pool."""
    if not UNPROCESSED_POOL.exists():
        return 0
    pdf_files = list(UNPROCESSED_POOL.glob("*.pdf")) + list(UNPROCESSED_POOL.glob("*.PDF"))
    return len(pdf_files)

def calculate_metrics(metrics):
    """Calculate dashboard metrics from parsed CSV data."""
    if not metrics:
        return {
            'total_processed': 0,
            'avg_time_per_file': 0.0,
            'total_tokens': 0,
            'latest_file': None,
            'latest_duration': 0,
            'latest_tokens': 0
        }

    total_processed = len(metrics)
    total_duration = sum(m['duration_in_seconds'] for m in metrics)
    avg_time = total_duration / total_processed if total_processed > 0 else 0.0
    total_tokens = sum(m['total_tokens'] for m in metrics)

    # Latest entry (most recent by end_time)
    latest = max(metrics, key=lambda x: x['end_time']) if metrics else None
    latest_file = latest['filename'] if latest else None
    latest_duration = latest['duration_in_seconds'] if latest else 0
    latest_tokens = latest['total_tokens'] if latest else 0

    return {
        'total_processed': total_processed,
        'avg_time_per_file': avg_time,
        'total_tokens': total_tokens,
        'latest_file': latest_file,
        'latest_duration': latest_duration,
        'latest_tokens': latest_tokens
    }

def format_seconds(seconds):
    """Format seconds into HH:MM:SS."""
    if seconds < 0:
        return "00:00:00"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def main():
    """Main dashboard loop."""
    print("GraphRAG Ingestion Telemetry Dashboard")
    print("=" * 50)
    print(f"CSV Path: {CSV_PATH}")
    print(f"Unprocessed Pool: {UNPROCESSED_POOL}")
    print(f"Refresh Interval: {REFRESH_INTERVAL}s")
    print("Press Ctrl+C to exit\n")

    try:
        while True:
            # Clear screen (works on both Windows and Unix)
            os.system('cls' if os.name == 'nt' else 'clear')

            # Read data
            metrics = read_csv_metrics()
            unprocessed_count = count_unprocessed_pdfs()
            calculated = calculate_metrics(metrics)

            # Calculate ETA
            remaining_files = unprocessed_count
            avg_time = calculated['avg_time_per_file']
            eta_seconds = remaining_files * avg_time if avg_time > 0 else 0

            # Display metrics
            print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("-" * 50)
            print(f"Total Files Processed: {calculated['total_processed']}")
            print(f"Remaining Files (Unprocessed Pool): {remaining_files}")
            print(f"Average Time per File: {format_seconds(avg_time)} ({avg_time:.2f}s)")
            print(f"Total Tokens Burned: {calculated['total_tokens']:,}")
            print(f"Estimated Time of Completion: {format_seconds(eta_seconds)}")
            print("-" * 50)
            if calculated['latest_file']:
                print(f"Latest Processed File:")
                print(f"  Filename: {calculated['latest_file']}")
                print(f"  Duration: {format_seconds(calculated['latest_duration'])} ({calculated['latest_duration']:.2f}s)")
                print(f"  Tokens: {calculated['latest_tokens']:,}")
            else:
                print("Latest Processed File: No data yet")
            print("-" * 50)

            time.sleep(REFRESH_INTERVAL)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    except Exception as e:
        print(f"\nUnexpected error: {e}")

if __name__ == "__main__":
    main()