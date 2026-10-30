import json
import time
import glob
import os

import json
import time
import glob
import os
import requests

API_URL = os.environ.get("GRAPHRAG_API_URL", "http://localhost:8000")

class NativeGraphRAGEngineClient:
    def __init__(self, api_url=None):
        self.api_url = api_url or API_URL

    def query(self, question: str):
        try:
            resp = requests.post(
                f"{self.api_url}/query",
                json={"query": question},
                timeout=120
            )
            if resp.status_code == 200:
                data = resp.json()
                return {"status": "SUCCESS", "answer": data.get("response", data.get("answer", ""))}
            else:
                return {"status": "FAILED", "answer": f"HTTP {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"status": "FAILED", "answer": str(e)}

try:
    print("[*] Initializing GraphRAG Evaluator Client...")
    engine = NativeGraphRAGEngineClient()
    print("[+] Client mapped to GraphRAG service endpoint.")
except Exception as e:
    print(f"[-] CRITICAL ENGINE FAILURE: Cannot initialize client. Error: {e}")
    exit(1)

OUTPUT_LOG = "graphrag_evaluation_results.json" 

def evaluate_response(status, answer, target_standards):
    if status == "FAILED":
        return "FAILED", 0.0

    answer_upper = str(answer).upper()
    
    if "N/A" in target_standards or not target_standards:
        refusal_keywords = ["DON'T KNOW", "DO NOT KNOW", "NOT MENTIONED", "NOT FOUND", "CANNOT ANSWER", "CONTAINS NO INFORMATION"]
        if any(kw in answer_upper for kw in refusal_keywords):
            return "CORRECT_REJECTION", 1.0
        return "HALLUCINATION", 0.0

    matched_standards = [std for std in target_standards if std.upper() in answer_upper]
    recall_score = len(matched_standards) / len(target_standards) if target_standards else 0.0
    
    evaluation_status = "VERIFIED" if recall_score == 1.0 else "PARTIAL_RETRIEVAL"
    if recall_score == 0.0:
        evaluation_status = "WRONG_CONTEXT"
        
    return evaluation_status, recall_score

def run_evaluation():
    print("\nInitializing Direct GraphRAG Evaluation Suite...")
    json_files = [f for f in sorted(glob.glob("*.json")) if f != OUTPUT_LOG]
    
    if not json_files:
        print("[ERROR] No .json files found. Exiting.")
        return

    evaluation_run_data = []

    for file_name in json_files:
        try:
            with open(file_name, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            continue
        
        if not isinstance(data, dict): continue
        queries = data.get("queries", [])
        if not queries or not isinstance(queries, list): continue

        print(f"\n--- Running {file_name} ---")

        for q in queries:
            if not isinstance(q, dict): continue
                
            query_id = q.get("id", "UNKNOWN_ID")
            question = q.get("query", "")
            target_standards = q.get("target_standards", [])
            
            print(f"Executing {query_id}...")
            start_time = time.time()
            
            try:
                # --- NATIVE INFERENCE EXECUTION ---
                # We call the engine directly instead of using requests.post()
                response = engine.query(question)
                
                # Extract the text answer from the engine's response object
                # (Adjust 'answer' to match your engine's actual output key if necessary)
                answer = response.get("answer", "") if isinstance(response, dict) else str(response)
                status = "SUCCESS"
            except Exception as e:
                answer = f"ERROR: NATIVE INFERENCE CRASH: {str(e)}"
                status = "FAILED"
                
            elapsed = time.time() - start_time
            eval_status, score = evaluate_response(status, answer, target_standards)
            
            result_payload = {
                "id": query_id,
                "question": question,
                "expected_targets": target_standards,
                "execution_status": status,
                "evaluation_status": eval_status,
                "retrieval_score": score,
                "latency_seconds": round(elapsed, 2),
                "answer": answer
            }
            evaluation_run_data.append(result_payload)
            
            with open(OUTPUT_LOG, "w", encoding="utf-8") as out_file:
                json.dump(evaluation_run_data, out_file, indent=2, ensure_ascii=False)
            
            # Cooldown interval for GPU offload
            time.sleep(2)

    total = len(evaluation_run_data)
    rejections = len([x for x in evaluation_run_data if x["evaluation_status"] == "CORRECT_REJECTION"])
    hallucinations = len([x for x in evaluation_run_data if x["evaluation_status"] == "HALLUCINATION"])
    verified = len([x for x in evaluation_run_data if x["evaluation_status"] == "VERIFIED"])
    
    print(f"\n[=== EVALUATION METRICS FOR THE 250 RUNS ===]")
    print(f"Total Queries Processed: {total}")
    print(f"Successful Poison Query Rejections: {rejections}")
    print(f"Failed Hallucinations: {hallucinations}")
    print(f"Perfect Multi-Hop Context Matches: {verified}")
    print(f"Structured logs written cleanly to {OUTPUT_LOG}")

if __name__ == "__main__":
    run_evaluation()