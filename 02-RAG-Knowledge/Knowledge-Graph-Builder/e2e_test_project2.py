"""End-to-end test for project2_tech — builds into the 'project2' database."""
import json
import requests
import time

BASE = "http://127.0.0.1:8080"
FOLDER = r"D:\RMFolder\RMPythonProjects\AI_Training\AI_GraphRAG\KnowledgegraphUIapp\input_files\project2_tech"

print("=" * 60)
print("END-TO-END TEST: project2_tech (database: project2)")
print("=" * 60)

# Step 0: Check databases
print("\n[0] Checking databases...")
resp = requests.get(f"{BASE}/api/databases", timeout=10)
dbs = resp.json()
print(f"  Databases: {dbs}")
db = "project2"

# Step 1: Browse
print("\n[1] Browsing project2_tech folder...")
resp = requests.get(f"{BASE}/api/browse", params={"path": FOLDER}, timeout=10)
data = resp.json()
files = [f["path"] for f in data.get("files", [])]
print(f"  Found {len(files)} files: {[f.split(chr(92))[-1] for f in files]}")

# Step 2: Propose
print("\n[2] Proposing schema via LLM...")
goals = ("Build a tech industry knowledge graph with companies, customers, products, "
         "purchases, and partnerships. I want to track which companies make which products, "
         "who buys them, and which companies partner with each other.")
t0 = time.time()
resp = requests.post(f"{BASE}/api/propose", json={
    "selected_files": files,
    "goals": goals,
    "database": db,
}, timeout=180)
t1 = time.time()
print(f"  Status: {resp.status_code} ({t1-t0:.1f}s)")
if resp.status_code != 200:
    print(f"  ERROR: {resp.text[:500]}")
    exit(1)

plan = resp.json()["plan"]
print(f"  Nodes: {list(plan.get('nodes', {}).keys())}")
print(f"  Relationships: {list(plan.get('relationships', {}).keys())}")

# Step 3: Build
print("\n[3] Building graph in Neo4j (database: project2)...")
t0 = time.time()
resp = requests.post(f"{BASE}/api/build", json={
    "plan": plan,
    "database": db,
}, timeout=120)
t1 = time.time()
print(f"  Status: {resp.status_code} ({t1-t0:.1f}s)")
if resp.status_code != 200:
    print(f"  ERROR: {resp.text[:500]}")
    exit(1)

result = resp.json()
summary = result["summary"]
print(f"  Nodes created: {summary['nodes_created']}")
print(f"  Relationships created: {summary['relationships_created']}")
print(f"  Errors: {len(summary['errors'])}")
if summary["errors"]:
    for err in summary["errors"]:
        print(f"    ✗ {err}")
if result.get("progress"):
    for msg in result["progress"]:
        print(f"    {msg}")

# Step 4: Stats
print("\n[4] Getting graph stats...")
resp = requests.get(f"{BASE}/api/stats", params={"database": db}, timeout=15)
stats = resp.json()
print(f"  Node counts: {stats.get('nodes', {})}")
print(f"  Relationship counts: {stats.get('relationships', {})}")

# Step 5: Graph data
print("\n[5] Getting graph data...")
resp = requests.get(f"{BASE}/api/graph", params={"database": db, "limit": 50}, timeout=15)
gdata = resp.json()
print(f"  Nodes: {len(gdata.get('nodes', []))}")
print(f"  Edges: {len(gdata.get('edges', []))}")

# Step 6: Query
print("\n[6] Querying the graph...")
question = "Which companies are in the Cloud Computing industry?"
resp = requests.post(f"{BASE}/api/query", json={
    "question": question,
    "database": db,
}, timeout=120)
print(f"  Status: {resp.status_code}")
if resp.status_code == 200:
    qresult = resp.json()
    if qresult.get("error"):
        print(f"  Error: {qresult['error']}")
    else:
        print(f"  Answer: {qresult.get('answer', '')[:300]}")
        print(f"  Cypher: {qresult.get('cypher', '')[:200]}")
else:
    print(f"  ERROR: {resp.text[:300]}")

print("\n" + "=" * 60)
print("END-TO-END TEST COMPLETE")
print("=" * 60)