#!/usr/bin/env python3
"""
Evaluation script for GraphRAG Engine using query_eso test suites.
Reads all 4 JSON files from query_eso/, posts queries to local API,
and validates responses against target_standards.
"""

import json
import requests
import time
import os
from datetime import datetime
from typing import List, Dict, Any, Tuple
from collections import defaultdict
import sys

def load_query_files() -> List[Dict[str, Any]]:
    """Load all 4 JSON files from query_eso directory."""
    import os
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
    QUERY_ESO_DIR = os.path.join(PROJECT_ROOT, "query_eso")
    query_dir = QUERY_ESO_DIR
    files = [
        "graphrag_test_suite_vol_1.json",
        "graphrag_test_suite_vol_2.json",
        "graphrag_test_suite_vol_3.json",
        "graphrag_test_suite_vol_4.json"
    ]

    all_queries = []
    for filename in files:
        filepath = os.path.join(query_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Add source file info to each query
                for query in data.get("queries", []):
                    query["source_file"] = filename
                all_queries.extend(data.get("queries", []))
            print(f"Loaded {len(data.get('queries', []))} queries from {filename}")
        except Exception as e:
            print(f"Error loading {filename}: {e}")

    return all_queries

def query_api(question: str) -> Dict[str, Any]:
    """Send query to the GraphRAG API."""
    import os
    API_URL = os.environ.get("GRAPHRAG_API_URL", "http://localhost:8000")
    try:
        response = requests.post(
            f"{API_URL}/query",
            json={"query": question},
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {
            "error": str(e),
            "answer": "",
            "sources": []
        }

def check_standards_in_response(response: Dict[str, Any], target_standards: List[str]) -> Tuple[bool, List[str], List[str]]:
    """
    Check if target standards are referenced in the answer or sources.
    Returns (all_found, found_standards, missing_standards)
    """
    answer_text = response.get("answer", "").upper()
    sources = response.get("sources", [])

    # Extract text from sources if available
    sources_text = ""
    for source in sources:
        if isinstance(source, dict):
            # Check various possible fields in source
            for field in ["document_name", "section_header", "chunk_id"]:
                if field in source and source[field]:
                    sources_text += " " + str(source[field]).upper()

    # Combined text to search
    combined_text = answer_text + " " + sources_text

    found = []
    missing = []

    for standard in target_standards:
        # Standardize the search - look for the standard name
        standard_upper = standard.upper().strip()
        if standard_upper in combined_text:
            found.append(standard)
        else:
            missing.append(standard)

    return (len(missing) == 0, found, missing)

def evaluate_queries(queries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate all queries and return results."""
    results = []
    stats = {
        "total": len(queries),
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "by_difficulty": defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0}),
        "by_hop_type": defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    }

    print(f"\nEvaluating {len(queries)} queries...")
    print("=" * 60)

    for i, query_data in enumerate(queries, 1):
        query_id = query_data.get("id", f"UNKNOWN_{i}")
        question = query_data.get("query", "")
        difficulty = query_data.get("difficulty", "Unknown")
        hop_type = query_data.get("hop_type", "Unknown")
        target_standards = query_data.get("target_standards", [])
        source_file = query_data.get("source_file", "unknown")

        print(f"[{i}/{len(queries)}] {query_id}: {question[:50]}...")

        # Query the API
        api_response = query_api(question)

        # Check for API errors
        if "error" in api_response:
            status = "ERROR"
            passed = False
            found_standards = []
            missing_standards = target_standards.copy()
            stats["errors"] += 1
        else:
            # Check if standards are present in response
            all_found, found_standards, missing_standards = check_standards_in_response(
                api_response, target_standards
            )

            if all_found:
                status = "PASS"
                passed = True
                stats["passed"] += 1
            else:
                status = "FAIL"
                passed = False
                stats["failed"] += 1

        # Update difficulty stats
        stats["by_difficulty"][difficulty]["total"] += 1
        if passed:
            stats["by_difficulty"][difficulty]["passed"] += 1
        else:
            stats["by_difficulty"][difficulty]["failed"] += 1

        # Update hop_type stats
        stats["by_hop_type"][hop_type]["total"] += 1
        if passed:
            stats["by_hop_type"][hop_type]["passed"] += 1
        else:
            stats["by_hop_type"][hop_type]["failed"] += 1

        # Store result
        result = {
            "query_id": query_id,
            "question": question,
            "difficulty": difficulty,
            "hop_type": hop_type,
            "target_standards": target_standards,
            "source_file": source_file,
            "status": status,
            "passed": passed,
            "found_standards": found_standards,
            "missing_standards": missing_standards,
            "answer_preview": api_response.get("answer", "")[:200] if "answer" in api_response else "",
            "has_error": "error" in api_response,
            "error_message": api_response.get("error", "") if "error" in api_response else ""
        }
        results.append(result)

        # Print immediate feedback
        if status == "PASS":
            print(f"  ✓ PASS - Found: {', '.join(found_standards)}")
        elif status == "FAIL":
            print(f"  ✗ FAIL - Missing: {', '.join(missing_standards)}")
        else:
            print(f"  ✗ ERROR - {api_response.get('error', 'Unknown error')}")

        # Small delay to avoid overwhelming the API
        time.sleep(0.5)

    return {
        "results": results,
        "stats": stats
    }

def generate_summary_report(evaluation_data: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a summary report from evaluation results."""
    stats = evaluation_data["stats"]

    # Calculate percentages
    total = stats["total"]
    passed = stats["passed"]
    failed = stats["failed"]
    errors = stats["errors"]

    pass_rate = (passed / total * 100) if total > 0 else 0

    # Difficulty breakdown
    difficulty_summary = {}
    for diff, diff_stats in stats["by_difficulty"].items():
        diff_total = diff_stats["total"]
        diff_passed = diff_stats["passed"]
        diff_rate = (diff_passed / diff_total * 100) if diff_total > 0 else 0
        difficulty_summary[diff] = {
            "total": diff_total,
            "passed": diff_passed,
            "failed": diff_stats["failed"],
            "pass_rate_percent": round(diff_rate, 1)
        }

    # Hop type breakdown
    hop_summary = {}
    for hop, hop_stats in stats["by_hop_type"].items():
        hop_total = hop_stats["total"]
        hop_passed = hop_stats["passed"]
        hop_rate = (hop_passed / hop_total * 100) if hop_total > 0 else 0
        hop_summary[hop] = {
            "total": hop_total,
            "passed": hop_passed,
            "failed": hop_stats["failed"],
            "pass_rate_percent": round(hop_rate, 1)
        }

    return {
        "summary": {
            "total_queries": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "pass_rate_percent": round(pass_rate, 1)
        },
        "by_difficulty": difficulty_summary,
        "by_hop_type": hop_summary
    }

def main():
    """Main execution function."""
    print("GraphRAG Engine Evaluation Suite")
    print("=" * 60)
    print(f"Started at: {datetime.now().isoformat()}")

    # Check if API is available
    try:
        health_response = requests.get("http://localhost:8000/health", timeout=5)
        if health_response.status_code == 200:
            health_data = health_response.json()
            print(f"API Health Check: OK - Models loaded: {sum(health_data.get('models_loaded', {}).values())}/6")
        else:
            print("Warning: API health check failed")
    except:
        print("Warning: Cannot connect to API. Make sure the server is running on localhost:8000")
        print("Start it with: uvicorn src.api.fastapi_service:app --host 0.0.0.0 --port 8000")
        # Don't exit - let the user decide if they want to continue anyway

    # Load queries
    queries = load_query_files()
    if not queries:
        print("Error: No queries loaded. Exiting.")
        return 1

    print(f"\nTotal queries to evaluate: {len(queries)}")

    # Run evaluation
    start_time = time.time()
    evaluation_data = evaluate_queries(queries)
    end_time = time.time()

    # Generate summary
    summary = generate_summary_report(evaluation_data)

    # Print final results
    print("\n" + "=" * 60)
    print("EVALUATION COMPLETE")
    print("=" * 60)
    print(f"Total time: {end_time - start_time:.1f} seconds")
    print(f"Total queries: {summary['summary']['total_queries']}")
    print(f"Passed: {summary['summary']['passed']}")
    print(f"Failed: {summary['summary']['failed']}")
    print(f"Errors: {summary['summary']['errors']}")
    print(f"Pass rate: {summary['summary']['pass_rate_percent']}%")

    print("\nBy Difficulty:")
    for difficulty, stats in summary["by_difficulty"].items():
        print(f"  {difficulty}: {stats['passed']}/{stats['total']} ({stats['pass_rate_percent']}%)")

    print("\nBy Hop Type:")
    for hop_type, stats in summary["by_hop_type"].items():
        print(f"  {hop_type}: {stats['passed']}/{stats['total']} ({stats['pass_rate_percent']}%)")

    # Save detailed results
    results_dir = os.path.join(QUERY_ESO_DIR, "results")
    os.makedirs(results_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_file = os.path.join(results_dir, f"eval_{timestamp}.json")

    full_report = {
        "timestamp": timestamp,
        "summary": summary,
        "detailed_results": evaluation_data["results"]
    }

    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(full_report, f, indent=2, ensure_ascii=False)

    print(f"\nDetailed results saved to: {summary_file}")

    # Also save a simple summary file for quick reference
    simple_summary = {
        "timestamp": timestamp,
        "pass_rate_percent": summary['summary']['pass_rate_percent'],
        "total_queries": summary['summary']['total_queries'],
        "passed": summary['summary']['passed'],
        "failed": summary['summary']['failed'],
        "errors": summary['summary']['errors']
    }

    simple_file = os.path.join(results_dir, f"summary_{timestamp}.json")
    with open(simple_file, 'w', encoding='utf-8') as f:
        json.dump(simple_summary, f, indent=2)

    print(f"Summary saved to: {simple_file}")

    return 0 if summary['summary']['errors'] == 0 else 1

if __name__ == "__main__":
    sys.exit(main())