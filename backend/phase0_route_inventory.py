import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from main import app


def main():
    routes = []
    for route in app.routes:
        if not hasattr(route, "methods"):
            continue
        methods = ",".join(sorted(route.methods - {"HEAD"}))
        routes.append((route.path, methods))

    for path, methods in sorted(routes):
        print(f"{methods:10} {path}")


if __name__ == "__main__":
    main()
