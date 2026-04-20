#!/usr/bin/env python
"""Check registered endpoints."""
import main

routes = [r for r in main.app.routes if hasattr(r, 'path')]
print(f"Total registered routes: {len(routes)}\n")
for route in routes:
    if hasattr(route, 'methods'):
        methods = ', '.join(route.methods)
        print(f"{methods:8} {route.path}")
