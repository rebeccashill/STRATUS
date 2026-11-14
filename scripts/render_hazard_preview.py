"""Offline, read-only layout proof when this environment blocks localhost sockets."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.hazards.harness import FixtureFleetHost


def main():
    web = ROOT / "stratus/inspection/web"
    folder = ROOT / "docs/evidence/inspection-0.0.2/part13"
    host = FixtureFleetHost(50)
    host.prepare("D001")
    host.report()
    data = json.dumps(host.snapshot(), allow_nan=False).replace("<", "\\u003c")
    css = (web / "hazards.css").read_text(encoding="utf-8")
    script = (web / "hazards.js").read_text(encoding="utf-8")
    bootstrap = """const offlineState=DATA;const root=document.getElementById('hazard-root');
    StratusHazards.mount(root,async()=>({state:offlineState})).start().then(()=>{
      const note=document.createElement('p');note.className='notice';note.textContent='READ-ONLY SAVED FIXTURE — visual layout review only. Live HTTP actions and Part 12 integration remain unverified.';root.prepend(note);
      root.querySelectorAll('button,input,select,textarea').forEach(n=>n.disabled=true);
    });""".replace("DATA", data)
    document = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>STRATUS hazard layout proof — read only</title><style>" + css + "</style>"
                "<main id='hazard-root' data-read-only='true'></main><script>" + script + "</script><script>" + bootstrap + "</script></html>")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "layout-proof-50.html"
    path.write_text(document, encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
