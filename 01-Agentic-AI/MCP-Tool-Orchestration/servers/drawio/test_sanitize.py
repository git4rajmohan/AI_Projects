import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from server import _sanitize_mermaid, _make_url

bad = (
    "flowchart TD\n"
    "%% Main Title\n"
    "classDef title fill:#2c3e50,color:white,stroke:#34495e,stroke-width:2px\n"
    "classDef usecase fill:#f39c12\n"
    'title["<b>Data Structure Operations</b>"]:::title\n'
    "A[Arrays] --> B[Search]\n"
    "B --> |found| C[Return Result]:::usecase\n"
    "%% End"
)

clean = _sanitize_mermaid(bad)
print("=== Sanitized ===")
print(clean)
print()
url = _make_url(clean, "mermaid")
print("URL OK, len:", len(url))

