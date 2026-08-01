#!/usr/bin/env python3
"""Legacy file server — use the FastAPI app instead:

    uvicorn backend.main:app --reload --port 8080
"""

print("This server is deprecated.")
print("Run:  uvicorn backend.main:app --reload --port 8080")
print("Then open http://localhost:8080 and sign in as admin / admin")
raise SystemExit(1)
