"""Author a reproducible synthetic image pack; never downloads inspection photos."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.inspection.png import encode_rgb  # noqa: E402

# Tiny block font keeps the SYNTHETIC watermark legible without installed fonts.
FONT = {
    "A": "01110/10001/10001/11111/10001/10001/10001",
    "C": "01111/10000/10000/10000/10000/10000/01111",
    "D": "11110/10001/10001/10001/10001/10001/11110",
    "E": "11111/10000/10000/11110/10000/10000/11111",
    "F": "11111/10000/10000/11110/10000/10000/10000",
    "G": "01111/10000/10000/10111/10001/10001/01111",
    "H": "10001/10001/10001/11111/10001/10001/10001",
    "I": "11111/00100/00100/00100/00100/00100/11111",
    "L": "10000/10000/10000/10000/10000/10000/11111",
    "N": "10001/11001/10101/10011/10001/10001/10001",
    "O": "01110/10001/10001/10001/10001/10001/01110",
    "P": "11110/10001/10001/11110/10000/10000/10000",
    "R": "11110/10001/10001/11110/10100/10010/10001",
    "S": "01111/10000/10000/01110/00001/00001/11110",
    "T": "11111/00100/00100/00100/00100/00100/00100",
    "U": "10001/10001/10001/10001/10001/10001/01110",
    "V": "10001/10001/10001/10001/10001/01010/00100",
    "W": "10001/10001/10001/10101/10101/11011/10001",
    "Y": "10001/10001/01010/00100/00100/00100/00100",
    "0": "01110/10001/10011/10101/11001/10001/01110",
    "1": "00100/01100/00100/00100/00100/00100/01110",
    "2": "01110/10001/00001/00010/00100/01000/11111",
    "3": "11110/00001/00001/01110/00001/00001/11110",
    "4": "00010/00110/01010/10010/11111/00010/00010",
    "5": "11111/10000/10000/11110/00001/00001/11110",
    "6": "01110/10000/10000/11110/10001/10001/01110",
    "-": "00000/00000/00000/11111/00000/00000/00000",
    " ": "00000/00000/00000/00000/00000/00000/00000",
}
W, H = 480, 320


def rectangle(pixels, x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(H, y1)):
        a, b = (y * W + max(0, x0)) * 3, (y * W + min(W, x1)) * 3
        pixels[a:b] = bytes(color) * max(0, min(W, x1) - max(0, x0))


def text(pixels, label, x, y, scale=2):
    for char in label:
        for row, bits in enumerate(FONT[char].split("/")):
            for col, bit in enumerate(bits):
                if bit == "1":
                    rectangle(pixels, x + col * scale, y + row * scale,
                              x + (col + 1) * scale, y + (row + 1) * scale,
                              (240, 245, 250))
        x += 6 * scale


def blur(pixels, radius=9):
    # Two separable box passes produce genuine raster blur, not a quality label.
    source = pixels
    for horizontal in (True, False):
        dest = bytearray(len(source))
        outer, inner = (H, W) if horizontal else (W, H)
        for a in range(outer):
            for channel in range(3):
                values = [source[((a * W + b) if horizontal else (b * W + a)) * 3 + channel]
                          for b in range(inner)]
                prefix = [0]
                for value in values:
                    prefix.append(prefix[-1] + value)
                for b in range(inner):
                    lo, hi = max(0, b - radius), min(inner, b + radius + 1)
                    index = ((a * W + b) if horizontal else (b * W + a)) * 3 + channel
                    dest[index] = (prefix[hi] - prefix[lo]) // (hi - lo)
        source = dest
    return source


def image(asset, view, condition):
    pixels = bytearray(bytes((42, 57, 59)) * W * H)
    follow = view == "follow-up"
    left, top, right, bottom = (32, 54, 448, 270) if follow else (66, 64, 414, 258)
    rectangle(pixels, left - 7, top - 7, right + 7, bottom + 7, (180, 193, 198))
    for row in range(6):
        for col in range(10):
            x0 = left + col * (right - left) // 10
            x1 = left + (col + 1) * (right - left) // 10
            y0 = top + row * (bottom - top) // 6
            y1 = top + (row + 1) * (bottom - top) // 6
            blue = 90 + (row * 7 + col * 3 + int(asset[-1]) * 4) % 32
            rectangle(pixels, x0 + 1, y0 + 1, x1 - 1, y1 - 1, (17, 47, blue))
    if condition == "concern":
        # Authored irregular scratch-like mark, never a real defect observation.
        for n in range(145):
            x = 180 + n
            y = 104 + n // 3 + ((n // 18) % 2) * 12
            rectangle(pixels, x, y, x + 3, y + 4, (243, 211, 113))
    elif condition == "glare":
        for y in range(90, 225):
            rectangle(pixels, 150 + (y - 90) // 4, y, 330, y + 1, (238, 238, 225))
    if condition == "blur":
        pixels = blur(pixels)
    rectangle(pixels, 0, 0, W, 40, (16, 25, 38))
    rectangle(pixels, 0, 281, W, H, (16, 25, 38))
    text(pixels, "SYNTHETIC - NO REAL FLIGHT", 12, 12)
    text(pixels, asset + " " + view.upper(), 12, 295)
    return encode_rgb(W, H, bytes(pixels), "STRATUS Part 2 procedural synthetic illustration")


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    folder = ROOT / "evidence/inspection/images"
    folder.mkdir(parents=True, exist_ok=True)
    mission_path = ROOT / "stratus/inspection/missions/solar-array-001.json"
    mission = json.loads(mission_path.read_text(encoding="utf-8"))
    scenario = mission["scenario_id"]
    entries, annotations = [], []
    for asset in mission["assets"]:
        asset_id = asset["asset_id"]
        for view in asset["planned_view_ids"]:
            condition = "clear"
            if asset_id == "P02" and view == "overview":
                condition = "blur"
            if asset_id == "P03":
                condition = "concern"
            if asset_id == "P05" and view == "overview":
                condition = "glare"
            evidence_id = f"{scenario}:{asset_id}:{view}"
            relative = f"evidence/inspection/images/{asset_id}-{view}.png"
            data = image(asset_id, view, condition)
            (ROOT / relative).write_bytes(data)
            entries.append({
                "evidence_id": evidence_id, "scenario_id": scenario,
                "asset_id": asset_id, "view_id": view, "image_path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "source_label": "synthetic", "source_mode": "procedural_synthetic",
                "source_note": "New STRATUS Part 2 procedural illustration; no source photograph or earlier project data.",
                "rights_note": "Self-authored demo fixture; no third-party image, attribution, or site permission required. Not diagnostic evidence.",
                "generator": "scripts/prepare_part2_evidence.py:v1",
            })
            unclear = condition in ("blur", "glare")
            finding = ("unknown" if unclear else "apparent_concern_review_required"
                       if condition == "concern" else "no_apparent_concern_in_synthetic_drawing")
            annotations.append({
                "evidence_id": evidence_id, "scenario_id": scenario,
                "assessment_mode": "authored_replay_annotation",
                "annotation_author": "AI-assisted scenario preparation; human review pending",
                "human_review_status": "pending", "live_model_output": False,
                "image_quality": "unclear" if unclear else "clear", "finding": finding,
                "note": {"clear": "Grid visible in the authored illustration; this is not a defect diagnosis.",
                         "blur": "Authored box-blurred overview; insufficient detail; request a distinct follow-up.",
                         "concern": "Authored scratch-like mark; tentative review flag only, not a verified defect.",
                         "glare": "Authored bright occlusion; hidden cells remain unknown."}[condition],
            })
    write_json(ROOT / "evidence/inspection/manifest.json", {
        "schema_version": "1", "scenario_id": scenario,
        "annotations_path": "evidence/inspection/annotations.json",
        "fixture_policy": "Every planner uses this same fixed case; requesting evidence changes no aircraft state.",
        "entries": entries,
    })
    write_json(ROOT / "evidence/inspection/annotations.json", {
        "schema_version": "1", "scenario_id": scenario,
        "notice": "Prepared replay annotations, not live vision inference or confirmed human review.",
        "annotations": annotations,
    })
    mission.update(schema_version="0.0.1", revision="0.0.1-part2",
                   readiness="local_evidence_validated", execution_mode="synthetic_evidence_replay",
                   evidence_manifest="evidence/inspection/manifest.json")
    for asset in mission["assets"]:
        if asset["asset_id"] == "P01":
            asset["coverage_state"] = "prior_clear_authored_annotation"
        elif asset["asset_id"] == "P02":
            asset["coverage_state"] = "prior_unclear_authored_annotation_follow_up_needed"
    for prior in mission["prior_records"]:
        prior.update(evidence_status="available_synthetic", source_class="synthetic",
                     assessment_mode="authored_replay_annotation",
                     evidence_ref=f"{scenario}:{prior['asset_id']}:{prior['view_id']}",
                     finding="unknown_pending_operator_review")
    write_json(mission_path, mission)
    print(f"Prepared {len(entries)} synthetic PNG views and separate annotations for {scenario}.")


if __name__ == "__main__":
    main()
