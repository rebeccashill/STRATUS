"""Run the existing inspection desk plus an explicitly labeled hazard fixture page."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.inspection.dashboard import Dashboard, make_server
from stratus.hazards.preview import FixturePreview, mount_routes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8773)
    parser.add_argument("--size", type=int, default=2)
    parser.add_argument("--computation", choices=("local", "wolfram"), default="local")
    args = parser.parse_args()
    desk = Dashboard(computation="local")
    preview = FixturePreview(ROOT, args.size, args.computation)
    server = mount_routes(make_server(desk, args.port), preview.dispatch)
    print(f"STRATUS hazard fixture preview: http://127.0.0.1:{server.server_port}/hazards", flush=True)
    print("Fixture host only; Part 12 fleet integration is pending. No hardware polled automatically.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        desk.close()


if __name__ == "__main__":
    main()
