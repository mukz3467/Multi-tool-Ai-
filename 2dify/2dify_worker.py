import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import requests
from gradio_client import Client, handle_file

SPACE = "decart-ai/lucy-edit-dev"
FPS = 24
FRAMES = 81
WINDOW_SECONDS = FRAMES / FPS
HEIGHT = 480
WIDTH = 832
GUIDANCE = 5
PROMPT = (
    "Transform the scene into a clean hand-drawn 2D cartoon animation. "
    "Convert people, faces, hair, clothing, objects, architecture and background "
    "into illustrated 2D shapes with consistent outlines and cel shading. "
    "Preserve identity, motion, expressions, framing and timing. "
    "No photorealism, no 3D, no CGI."
)

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode:
        raise RuntimeError(p.stdout[-4000:])
    return p.stdout

def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return float(out.strip())

def fingerprint(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def download_result(data, dst):
    def walk(x):
        if isinstance(x, str) and x.startswith(("http://", "https://")):
            return x
        if isinstance(x, dict):
            for k in ("url", "path"):
                v = x.get(k)
                if isinstance(v, str) and v.startswith(("http://", "https://")):
                    return v
            for v in x.values():
                found = walk(v)
                if found:
                    return found
        if isinstance(x, (list, tuple)):
            for v in x:
                found = walk(v)
                if found:
                    return found
        return None

    url = walk(data)
    if not url:
        raise RuntimeError("Lucy returned no downloadable video.")
    response = requests.get(url, timeout=600)
    response.raise_for_status()
    Path(dst).write_bytes(response.content)
    if Path(dst).stat().st_size < 1024:
        Path(dst).unlink(missing_ok=True)
        raise RuntimeError("Downloaded result is unexpectedly small; chunk not checkpointed.")

def process(input_video, output_video):
    source = Path(input_video).resolve()
    target = Path(output_video).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    # Keep completed chunks beside the output so a restarted runtime can resume.
    work = target.parent / (target.stem + ".2dify_chunks")
    work.mkdir(parents=True, exist_ok=True)
    manifest_path = work / "manifest.json"
    total = duration(source)
    count = math.ceil(total / WINDOW_SECONDS)
    identity = {
        "source": source.name,
        "source_sha256": fingerprint(source),
        "duration": round(total, 3),
        "space": SPACE,
        "fps": FPS,
        "frames": FRAMES,
        "prompt": PROMPT,
    }
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old.get("identity") != identity:
            raise RuntimeError(
                f"Checkpoint folder {work} belongs to a different input/settings. "
                "Rename or remove that folder before starting a new job."
            )
    else:
        manifest_path.write_text(json.dumps({"identity": identity, "completed": []}, indent=2),
                                 encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    client = Client(SPACE)
    print(f"Input {total:.1f}s | {count} windows | checkpoint folder: {work}")

    for i in range(count):
        raw = work / f"raw_{i:05d}.mp4"
        edited = work / f"edited_{i:05d}.mp4"
        # A valid saved output is the checkpoint; skip it after interruption.
        if edited.exists() and edited.stat().st_size > 1024:
            if i not in manifest["completed"]:
                manifest["completed"].append(i)
                manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(f"[{i+1}/{count}] already complete — skipping")
            continue

        start = i * WINDOW_SECONDS
        run([
            "ffmpeg", "-y", "-ss", f"{start:.6f}", "-i", str(source),
            "-t", f"{WINDOW_SECONDS:.6f}", "-an", "-vf", f"fps={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", str(raw)
        ])
        print(f"[{i+1}/{count}] sending {start:.2f}s to Lucy…")
        job = client.submit(
            handle_file(str(raw)), PROMPT, "", FRAMES, True,
            HEIGHT, WIDTH, GUIDANCE, api_name="/process_video"
        )
        download_result(job.result(), edited)
        manifest["completed"] = sorted(set(manifest["completed"] + [i]))
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"[{i+1}/{count}] saved checkpoint")

    concat = work / "concat.txt"
    concat.write_text(
        "\n".join("file '" + p.as_posix().replace("'", "'\\''") + "'"
                   for p in [work / f"edited_{i:05d}.mp4" for i in range(count)]),
        encoding="utf-8"
    )
    temp_output = target.with_name(target.stem + ".assembling.mp4")
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        str(temp_output)
    ])
    temp_output.replace(target)
    print(f"COMPLETE: {target}")
    print(f"Checkpoints retained at: {work}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python 2dify_worker.py input.mp4 output.mp4")
        raise SystemExit(2)
    process(sys.argv[1], sys.argv[2])
