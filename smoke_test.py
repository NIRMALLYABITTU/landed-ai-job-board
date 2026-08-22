"""Local smoke test for the Fielded Flask application.

Run from the project directory after installing requirements and building the DB:
    python smoke_test.py
"""
from app import app


def main():
    with app.test_client() as client:
        checks = [
            ("/api/health", 200),
            ("/api/stats", 200),
            ("/api/sources", 200),
            ("/api/jobs?search=Python&per_page=3", 200),
        ]
        for path, expected in checks:
            response = client.get(path)
            if response.status_code != expected:
                raise SystemExit(f"FAIL {path}: HTTP {response.status_code}: {response.get_data(as_text=True)[:500]}")
            data = response.get_json()
            print(f"PASS {path}: HTTP {response.status_code}")
            if path.startswith("/api/jobs"):
                print(f"  jobs returned: {len(data.get('jobs', []))}, total matches: {data.get('total')}")
            if path == "/api/health":
                print(f"  database jobs: {data.get('database_jobs')}, sources: {data.get('sources')}")

        print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()
