"""Local data-only stdio worker. Fresh process means a fresh optional HID session."""

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import queue
import sys
import threading
from types import SimpleNamespace

from .actions import strict_json


def serve(reader, incoming, outgoing):
    try:
        while True:
            line = incoming.readline(2049)
            if not line: return
            if len(line) > 2048: raise ValueError('Sensor command exceeds its bound')
            command = strict_json(line, max_chars=2048)
            if command == {'operation': 'close'}: return
            if command != {'operation': 'sample'}:
                raise ValueError('Unsupported sensor operation')
            # Optional library diagnostics cannot become a JSON protocol reply.
            with redirect_stdout(sys.stderr): data = reader.sample()
            outgoing.write(json.dumps(data, allow_nan=False)+'\n')
            outgoing.flush()
    finally:
        reader.close()


def receive_commands(incoming, commands, on_eof):
    """Parent pipe loss ends the worker even if the sensor thread is blocked."""
    try:
        while True:
            line = incoming.readline(2049)
            if not line: return
            commands.put(line, timeout=0.2)
    finally:
        on_eof()


def main():
    from .ground import HardwareReader
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    # Sensor acquisition needs only its context directory, not aircraft/image inputs.
    root = args.root.resolve()
    if not root.is_dir(): parser.error('Sensor project root does not exist')
    mission = SimpleNamespace(project_root=root)
    commands = queue.Queue(maxsize=2)
    threading.Thread(target=receive_commands,
        args=(sys.stdin, commands, lambda:os._exit(0)), daemon=True).start()
    class Incoming:
        def readline(self, _limit): return commands.get()
    serve(HardwareReader(mission), Incoming(), sys.stdout)


if __name__ == '__main__': main()
