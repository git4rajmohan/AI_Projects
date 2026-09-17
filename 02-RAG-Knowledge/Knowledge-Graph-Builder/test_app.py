"""Quick test script for KnowledgegraphUIapp."""
from app.graph_builder import list_input_files
from app.query_engine import answer_question

# Test 1: list files
files = list_input_files()
print(f"Found {len(files)} files:")
for f in files:
    if "filename" in f:
        rows = f.get("row_count", "?")
        print(f"  {f['filename']:35s} {rows:>5} rows  cols: {f.get('columns', [])}")

# Test 2: import check
print("\nAll modules imported successfully.")