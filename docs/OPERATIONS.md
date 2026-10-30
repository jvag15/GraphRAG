# ROUTINES.md — Standard Operating Procedures

# GraphRAG Engine — Legal & Regulatory Compliance Intelligence Engine

# Read CLAUDE.md and AGENTS.md first

---

## WHAT THIS FILE IS

Step-by-step procedures for every recurring task. Each routine is self-contained.
Follow each step exactly. Do not skip or reorder.

"Run on server (SSH):" = SSH into graphrag-automation@127.0.0.1
"Run in Windows PowerShell:" = dev machine at graphrag_engine\

---

## ROUTINE 1 — QUERY SERVER STARTUP (port 8000)

Use when starting the query server for auditor use or eval runs.
**Prerequisites:** Ingestion must NOT be running. Port 8080 must be free.

```bash
# Run on server (SSH):
cd /home/graphrag-automation/graphrag_engine
source venv/bin/activate

# Kill anything on port 8000 and 8080 before starting
fuser -k 8000/tcp
fuser -k 8080/tcp
pkill -9 -f llama_cpp.server 2>/dev/null

# Verify models are present
ls -lh models/
# Must show: bge-large-en-v1.5/, bge-reranker-v2-m3/, Qwen3.6-12B-IQ-Q4_K_M.gguf

# Confirm .env is readable
cat .env | grep -E "QWEN_MODEL_PATH|RERANKER_MODEL_PATH|EMBED_MODEL_PATH"

# Start query server
tmux new-session -s queryserver
uvicorn src.api.fastapi_service:app --host 0.0.0.0 --port 8000 --log-level info
```

**Expected startup sequence:**

1. `Loading weights: 100%` — BGE embed loading
2. `Embedding model loaded on GPU: NVIDIA GeForce RTX 3060`
3. `Reranker loaded. VRAM used: X.XX GB`
4. `Reranker loaded successfully`
5. `Reranker injected successfully`
6. `Indices loaded. ChromaDB docs: 2224, Graph nodes: 6115, edges: 4246`
7. `Qwen LLM loaded successfully. Threads: 8, GPU layers: all`
8. `Query router using shared Qwen instance.`
9. `ConversationManager initialized`
10. `Anthropic client initialized` (if ANTHROPIC_API_KEY set) or `OpenAI client initialized` (if OPENAI_API_KEY set) or `Local Qwen generation mode active` (if neither key is set)
11. `GraphRAG Engine fully loaded and ready.`
12. `Application startup complete.`
13. `Uvicorn running on http://0.0.0.0:8000`

**Smoke test:**

```bash
curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the purpose of AS 1 Disclosure of Accounting Policies?"}' \
  | python3 -m json.tool
```

Response must contain: `answer`, `sources`, `session_id`, `has_sufficient_context: true`.
Check the terminal output for which generation mode is active:

- `[GEN] Anthropic Sonnet` = using Claude Sonnet
- `[GEN] OpenAI GPT-4o-mini` = using GPT-4o-mini
- `[GEN] Local Qwen` = using local model (testing mode)

---

## ROUTINE 2 — LLM INFERENCE SERVER STARTUP (port 8080)

Use when starting ingestion. Must be running before graph_builder.py is called.
**Prerequisites:** Query server (port 8000) must be STOPPED first.

```bash
# Run on server (SSH):
cd /home/graphrag-automation/graphrag_engine
source venv/bin/activate

# Kill query server first
fuser -k 8000/tcp
tmux kill-session -t queryserver 2>/dev/null

# Set required memory environment
export LD_PRELOAD=/usr/lib/libjemalloc.so
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Start the LLM inference server (Llama 3.1 8B)
tmux new-session -s llmserver
export LD_PRELOAD=/usr/lib/libjemalloc.so
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
python -m llama_cpp.server \
  --model /home/graphrag-automation/graphrag_engine/models/Meta-Llama-3.1-8B-Instruct-Q8_0.gguf \
  --host 127.0.0.1 \
  --port 8080 \
  --n_gpu_layers -1 \
  --n_threads 8

# Verify it's up (in second SSH window):
curl -s http://127.0.0.1:8080/v1/models | python3 -m json.tool
```

**If port 8080 is stuck from a previous session:**

```bash
pkill -9 -f llama_cpp.server
fuser -k 8080/tcp
```

---

## ROUTINE 3 — FULL EVALUATION RUN

Use after any code change to verify the system against baseline.
**Prerequisites:** Query server running (Routine 1 complete, smoke test passed).

```bash
# Run on server (SSH) — new tmux window:
cd /home/graphrag-automation/graphrag_engine
source venv/bin/activate
python run_eval.py
```

Takes ~30-35 minutes. Results written to `query_eso/results/eval_TIMESTAMP.json`.

```bash
# Check summary after completion:
ls -lt query_eso/results/
cat query_eso/results/summary_*.json | python3 -m json.tool
```

**Pass criteria:** 95+/100 = acceptable. 100/100 = baseline. Below 95 = regression.
Known acceptable fallbacks (always return knowledge-base message, not failures):
TEST_049, TEST_059, TEST_082, TEST_086, TEST_092, TEST_095, TEST_099

---

## ROUTINE 4 — FILE TRANSFER (Windows → Server)

**Rule:** Never scp the .env file. It is chmod 444 on the server.

```powershell
# Run in Windows PowerShell:
# Individual files (preferred):
scp "graphrag_engine\src\api\fastapi_service.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/src/api/
scp "graphrag_engine\src\extraction\graph_builder.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/src/extraction/
scp "graphrag_engine\src\extraction\graph_io.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/src/extraction/
scp "graphrag_engine\src\retrieval\hybrid_search.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/src/retrieval/
scp "graphrag_engine\src\retrieval\query_router.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/src/retrieval/
scp "graphrag_engine\src\retrieval\reranker.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/src/retrieval/
scp "graphrag_engine\run_ingestion.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/
scp "graphrag_engine\run_eval.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/
scp "graphrag_engine\batch_coordinator.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/

# GUI files:
scp -r "graphrag_engine\gui" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/

# Whole src/ (when many files changed):
scp -r "graphrag_engine\src" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/
```

**Verify after transfer:**

```bash
# Run on server (SSH):
python3 -c "import src.api.fastapi_service; print('Import OK')"
```

Must print "Import OK" with no errors before restarting anything.

---

## ROUTINE 5 — BATCH INGESTION (fault-tolerant, BATCH_SIZE=1)

Use when adding new documents through the staging pipeline.
**Prerequisites:** Query server (port 8000) and LLM server (port 8080) both STOPPED.
LLM server will be launched automatically by batch_coordinator.py or must be started before.

```bash
# Run on server (SSH):
cd /home/graphrag-automation/graphrag_engine
source venv/bin/activate

# Kill query server
fuser -k 8000/tcp
tmux kill-session -t queryserver 2>/dev/null

# Required memory environment — must be set every time
export LD_PRELOAD=/usr/lib/libjemalloc.so
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Verify staging has files
ls /opt/graphrag/data/ingestion_pool/staging/ | wc -l

# Start LLM server first (port 8080)
# (follow Routine 2, then return here)

# Run batch coordinator in tmux
tmux new-session -s batch
export LD_PRELOAD=/usr/lib/libjemalloc.so
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
source venv/bin/activate
python batch_coordinator.py
# Detach: Ctrl+B, D
# Reattach: tmux attach -t batch
```

**Monitor progress:**

```bash
# In second window — telemetry dashboard:
python telemetry_dashboard.py

# Or manual check:
watch -n 30 'python3 -c "
import json
d = json.load(open(\"/home/graphrag-automation/graphrag_engine/data/ingestion_log.json\"))
from collections import Counter
c = Counter(v[\"status\"] for v in d.values())
print(c)
"'

# Check quarantine for failures:
ls /opt/graphrag/data/ingestion_pool/quarantine/
# .error.log files contain full Python tracebacks
```

**File flow:**
`staging/` → processing (subprocess) → `archive/` on success
`staging/` → processing (subprocess) → `quarantine/` + `.error.log` on failure

---

## ROUTINE 6 — RESUMING INTERRUPTED INGESTION

Use when ingestion crashed and needs to restart from where it left off.

```bash
# Run on server (SSH):
cd /home/graphrag-automation/graphrag_engine
source venv/bin/activate

# Check where it stopped:
python3 -c "
import json
d = json.load(open('data/ingestion_log.json'))
from collections import Counter
c = Counter(v['status'] for v in d.values())
print(c)
"
```

**If crashed during Stage 3 (graph building):**

```bash
python3 -c "
import json
with open('data/ingestion_log.json') as f:
    log = json.load(f)
for k in log:
    if log[k]['status'] in ('graph_built', 'indexed', 'complete'):
        log[k]['status'] = 'embedded'
with open('data/ingestion_log.json', 'w') as f:
    json.dump(log, f, indent=2)
print('Reset complete')
"
rm -f data/knowledge_graph.json data/bm25_index/bm25.pkl
# Restart Routine 5
```

**If crashed during Stage 2 (embedding):**

```bash
python3 -c "
import json
with open('data/ingestion_log.json') as f:
    log = json.load(f)
for k in log:
    log[k]['status'] = 'chunked'
with open('data/ingestion_log.json', 'w') as f:
    json.dump(log, f, indent=2)
print('Reset complete')
"
rm -rf data/chroma_db/
# Restart Routine 5
```

---

## ROUTINE 7 — SERVER HEALTH CHECK

Run when something seems wrong.

```bash
# Run on server (SSH):
cd /home/graphrag-automation/graphrag_engine
source venv/bin/activate

# 1. VRAM usage
nvidia-smi

# 2. Port status
fuser 8000/tcp  # Query server
fuser 8080/tcp  # LLM inference server

# 3. Processes
ps aux | grep -E "uvicorn|llama_cpp|python"

# 4. Python version (must be 3.11.9)
python --version

# 5. .env loaded correctly
python3 -c "
from dotenv import load_dotenv; load_dotenv()
import os
keys = ['EMBED_MODEL_PATH', 'QWEN_MODEL_PATH', 'RERANKER_MODEL_PATH',
        'LLAMA_MODEL_PATH', 'LLM_API_URL', 'HDD_BASE_PATH']
for k in keys:
    v = os.environ.get(k, 'MISSING')
    print(f'{k}: {v}')
"
# All must print actual values, not MISSING

# 6. ChromaDB
python3 -c "
import chromadb
client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('legal_chunks')
print(f'ChromaDB docs: {col.count()}')
"

# 7. Knowledge graph
python3 -c "
import json
with open('data/knowledge_graph.json') as f:
    d = json.load(f)
print(f'Nodes: {len(d[\"nodes\"])}, Edges: {len(d[\"edges\"])}')
"

# 8. CPU governor
cpupower frequency-info | grep 'current policy'
# Must show: performance
# Fix if wrong: sudo cpupower frequency-set -g performance

# 9. jemalloc available
ls /usr/lib/libjemalloc.so
# Must exist. Install if missing: sudo pacman -S jemalloc
```

---

## ROUTINE 8 — ADDING A NEW DEPENDENCY

```bash
# Step 1 — Add to requirements.txt on Windows
# Step 2 — Transfer (Windows PowerShell):
scp "graphrag_engine\requirements.txt" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/

# Step 3 — Install on server (SSH):
cd /home/graphrag-automation/graphrag_engine
source venv/bin/activate
pip install packagename --no-cache-dir

# Step 4 — Verify:
python3 -c "import packagename; print('OK')"

# Step 5 — Note in CHANGES_SUMMARY.md
```

**Special case — llama-cpp-python upgrade:**

```bash
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python \
  --upgrade --no-cache-dir --force-reinstall
```

---

## ROUTINE 9 — LAUNCHING THE PYQT6 GUI

**Prerequisites:** Query server running on port 8000 (Routine 1 complete).
Must run on the Arch Linux machine with an active GNOME display session.

```bash
# Run directly in GNOME terminal on the Arch machine:
cd /home/graphrag-automation/graphrag_engine
source venv/bin/activate

# Required for QWebEngineView on Wayland
export QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"

python gui/main.py
```

**If testing GUI from Windows without the real backend:**

```bash
# Run in Windows PowerShell — start mock API first:
cd graphrag_engine
python mock_api.py
# Then launch the GUI against localhost:8000
```

**Install dependencies if not yet installed (on Arch server):**

```bash
sudo pacman -S --needed python-pyqt6 python-pyqt6-webengine
pip install PyQt6 PyQt6-WebEngine pyvis httpx
```

---

## ROUTINE 10 — DEPLOYING SYSTEMD TIMERS (nightly ingestion — post July 3rd)

```bash
# Run on server (SSH):
sudo cp systemd_configs/graphrag_ingest.service /etc/systemd/system/
sudo cp systemd_configs/graphrag_ingest_nightly.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now graphrag_ingest_nightly.timer
systemctl list-timers graphrag_ingest_nightly.timer
```

**To switch back to manual:**

```bash
sudo systemctl disable --now graphrag_ingest_nightly.timer
```

---

## ROUTINE 11 — UPDATING PROJECT DOCS AFTER A SESSION

Agents cannot update CLAUDE.md directly. Process:

1. At end of session, write `CLAUDE_UPDATES_[date].md` in project root with:
   - Which section needs updating
   - Exact new text to replace it with
2. Joel reviews, approves, applies changes manually.
3. Delete `CLAUDE_UPDATES_[date].md` after applied.

**Sections most likely to need updating:**

- `## CURRENT STATUS` — after pipeline milestones
- `## NEXT STEPS IN ORDER` — remove completed, add new
- `## COMPLETE BUG HISTORY` — add newly fixed bugs
- `## FILE STRUCTURE` — add new files
- `## MODELS` — if model paths or configs changed

---

## ROUTINE 12 — MONITORING TELEMETRY DASHBOARD

Use during long ingestion runs to track progress and ETA.

```bash
# Run on server (SSH) — new tmux window:
cd /home/graphrag-automation/graphrag_engine
source venv/bin/activate
python telemetry_dashboard.py
```

Dashboard shows:

- Current file being processed
- Stage (1-4) and progress within stage
- Tokens per second (entity extraction rate)
- Rolling average seconds per file
- Estimated time to completion
- Files completed / total / in quarantine

Metrics are also logged continuously to `logs/ingestion_metrics.csv`.

---

## ROUTINE 13 — HARDWARE THERMAL OVERRIDE

Use when the server's fans are locked at high RPMs during idle, or when suspecting
that `fancontrol` or `thermald` is interfering with NVIDIA VBIOS fan control.

```bash
# Run on server (SSH):

# Step 1 — Disable software fan controllers
sudo systemctl stop fancontrol 2>/dev/null && echo "fancontrol stopped"
sudo systemctl disable fancontrol 2>/dev/null
sudo systemctl stop thermald 2>/dev/null && echo "thermald stopped"
sudo systemctl disable thermald 2>/dev/null

# Step 2 — Return NVIDIA fan to VBIOS auto control
nvidia-settings -a "[gpu:0]/GPUFanControlState=0" 2>/dev/null
# 0 = automatic VBIOS curve, 1 = manual override

# Step 3 — Verify fan is responding normally
nvidia-smi --query-gpu=temperature.gpu,fan.speed,power.draw --format=csv,noheader
# Idle expected: ~40°C, 0-30% fan, <20W
# If fan.speed shows 100% at idle after this step, reboot the server
# to flush any persistent kernel fan state

# Step 4 — Monitor during sustained inference
watch -n 2 'nvidia-smi --query-gpu=temperature.gpu,fan.speed,power.draw,utilization.gpu \
  --format=csv,noheader'
# Normal during Qwen/Llama inference: 65-80°C, 50-75% fan, 110-170W, 85-96%
# Emergency threshold: >90°C — stop inference immediately, check airflow
```

**Normal operating ranges (RTX 3060):**

| State | GPU Temp | Fan | Power |
|---|---|---|---|
| Idle | 35-50°C | 0-30% | 10-20W |
| BGE embedding | 55-65°C | 30-50% | 60-90W |
| Llama/Qwen inference | 65-80°C | 50-75% | 110-170W |
| Throttle threshold | >90°C | 100% | hardware throttle |

---

## ROUTINE 14 — QUERY SERVER AUTO-LAUNCH (via ServerManager)

From Phase 3 onward, the GUI manages the query server lifecycle automatically
through `gui/services/server_manager.py`. Manual server launch (Routine 1) is
still required when the GUI is not running or when debugging backend issues.

**Verify ServerManager is working:**

```bash
# On server (SSH) — check that QueryTab successfully binds port 8000:
watch -n 2 'fuser 8000/tcp && echo "Port 8000 BOUND" || echo "Port 8000 FREE"'
# Launch gui/main.py in GNOME terminal, navigate to Query Tab
# Port 8000 should bind within 10-15 seconds of tab initialisation
```

**If ServerManager fails to bind port 8000:**

```bash
# Check what's blocking:
sudo lsof -i :8000
sudo fuser -v 8000/tcp

# Manual fallback (Routine 1):
fuser -k 8000/tcp && fuser -k 8080/tcp
source venv/bin/activate
uvicorn src.api.fastapi_service:app --host 0.0.0.0 --port 8000 --log-level info
```

---

## ROUTINE 15 — QUARANTINE AUDIT

Use to review files that were auto-quarantined by the ingestion pipeline.

```bash
# Run on server (SSH):
QUARANTINE=/opt/graphrag/data/ingestion_pool/quarantine

# List quarantined files and their error logs:
ls -lh $QUARANTINE/*.pdf $QUARANTINE/*.PDF 2>/dev/null
echo "---"
ls -lh $QUARANTINE/*.error.log 2>/dev/null

# Read a specific error log:
cat "$QUARANTINE/filename.pdf.error.log"

# Re-attempt ingestion for a repaired file (move back to staging):
mv "$QUARANTINE/repaired_file.pdf" \
   /opt/graphrag/data/ingestion_pool/staging/
# Then run Routine 5 (batch ingestion)

# Permanently discard a quarantined file:
rm "$QUARANTINE/bad_file.pdf" "$QUARANTINE/bad_file.pdf.error.log" 2>/dev/null
```

**Common quarantine reasons and fixes:**

| Error | Cause | Fix |
|---|---|---|
| `No /Root object!` | Corrupt or truncated PDF | Re-download the original document |
| `Unsupported extension` | `.error.log`, `.tmp` etc. in staging | They are moved automatically in Phase 3; if pre-Phase 3, delete manually |
| `PdfReadError` | PDF is password-protected or malformed | Obtain an unprotected version |
| `EOF marker not found` | Partial download / incomplete file | Re-download |

---

## ROUTINE 16 — EVALUATING DIRECTLY (HEADLESS, NO HTTP)

For regression testing and bulk evaluation when HTTP routing is impractical.
See SKILL.md Section 3 for the doctrine behind direct import.

```bash
# Run on server (SSH):
cd /home/graphrag-automation/graphrag_engine
source venv/bin/activate

# Direct import evaluation — does not require uvicorn running:
python3 - << 'PYEOF'
import sys
sys.path.insert(0, "/home/graphrag-automation/graphrag_engine")

from src.retrieval.hybrid_search import HybridSearchEngine
from src.retrieval.query_router import QueryRouter
# etc — initialise components directly

# Run a single query without HTTP:
engine = HybridSearchEngine()
engine.load_indices()
result = engine.search("What is AS 1?")
print(result)
PYEOF
```

**When to use direct import vs HTTP:**

| Scenario | Use |
|---|---|
| 100-question regression suite (`run_eval.py`) | Direct import — no uvicorn needed |
| Single query debugging | Direct import |
| Testing API contract (request/response shape) | HTTP via uvicorn |
| GUI integration test | HTTP via uvicorn |
| Performance benchmarking of full stack | HTTP via uvicorn |
