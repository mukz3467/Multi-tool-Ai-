import os
import sys
import math
import shutil
import subprocess
import tempfile
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
    out = run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)])
    return float(out.strip())

def download_result(data, dst):
    def walk(x):
        if isinstance(x, str) and x.startswith(("http://","https://")):
            return x
        if isinstance(x, dict):
            for k in ("url","path"):
                if isinstance(x.get(k), str) and x[k].startswith(("http://","https://")):
                    return x[k]
            for v in x.values():
                z = walk(v)
                if z: return z
        if isinstance(x, (list,tuple)):
            for v in x:
                z = walk(v)
                if z: return z
        return None
    url = walk(data)
    if not url:
        raise RuntimeError("Lucy returned no downloadable video.")
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    Path(dst).write_bytes(r.content)

def process(input_video, output_video):
    input_video = Path(input_video)
    output_video = Path(output_video)
    work = Path(tempfile.mkdtemp(prefix="2dify_"))
    try:
        total = duration(input_video)
        count = math.ceil(total / WINDOW_SECONDS)
        outputs = []
        client = Client(SPACE)

        print(f"Input: {total:.1f}s | windows: {count} | window: {WINDOW_SECONDS:.3f}s")
        for i in range(count):
            start = i * WINDOW_SECONDS
            raw = work / f"raw_{i:04d}.mp4"
            edited = work / f"edited_{i:04d}.mp4"

            # Exact 81-frame windows at 24 fps. The final window may be shorter.
            run([
                "ffmpeg","-y","-ss",f"{start:.6f}","-i",str(input_video),
                "-t",f"{WINDOW_SECONDS:.6f}","-an",
                "-vf",f"fps={FPS}",
                "-c:v","libx264","-pix_fmt","yuv420p","-preset","veryfast",
                str(raw)
            ])

            print(f"[{i+1}/{count}] Sending {start:.2f}s to Lucy…")
            job = client.submit(
                handle_file(str(raw)),
                PROMPT,
                "",
                FRAMES,
                True,
                HEIGHT,
                WIDTH,
                GUIDANCE,
                api_name="/process_video",
            )
            result = job.result()
            download_result(result, edited)
            outputs.append(edited)

        concat = work / "concat.txt"
        concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in outputs), encoding="utf-8")
        run([
            "ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),
            "-an","-c:v","libx264","-pix_fmt","yuv420p","-preset","veryfast",
            str(output_video)
        ])
        print(f"DONE: {output_video}")
    finally:
        shutil.rmtree(work, ignore_errors=True)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python 2dify_worker.py input.mp4 output.mp4")
        raise SystemExit(2)
    process(sys.argv[1], sys.argv[2])
