"""Benchmarks every commit of a pull request and checks that none changes the rendered output.

Usage: bench.py BASE_SHA OUT_DIR

For each commit after BASE_SHA, starting at the one that adds this script, this builds that commit's `src` with this checkout's examples,
then:
- runs the timed bench scenes and records frame time, GPU pass time and firefly system CPU time,
- renders the screenshot-only bench scenes and the examples in REGRESSION_EXAMPLES.

The first commit is the reference: every later commit's images must match it exactly.
Results go to OUT_DIR/<short sha>/ and a markdown summary to OUT_DIR/summary.md.
"""

import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

TIMED_SCENES = ["lights", "tiles", "moving"]
CHECK_SCENES = ["lights_scaled", "lights_fixed", "moving_rotated", "sprites", "sprites_scaled"]
REGRESSION_EXAMPLES = ["simple", "shapes", "crates", "flashlight", "blending", "fov", "render_layers", "test"]
FEATURES = "bevy/bevy_ci_testing,bevy/trace_chrome"
TARGET = Path("target/release/examples")
SCREENSHOT_CONFIG = Path(".github/ci/screenshot.ron").resolve()


def run(cmd, **kwargs):
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, check=True, **kwargs)


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def xvfb(cmd, env, log, cwd=None):
    with open(log, "w") as f:
        status = subprocess.run(
            ["timeout", "900", "xvfb-run", "-a", "-s", "-screen 0 1280x720x24", *cmd],
            env={**os.environ, "BEVY_ASSET_ROOT": str(Path.cwd()), **env},
            cwd=cwd,
            stdout=f,
            stderr=subprocess.STDOUT,
        ).returncode
    text = Path(log).read_text(errors="replace")
    errors = [line for line in text.splitlines() if " ERROR " in line or "panicked" in line]
    return status, errors


def system_times(trace_path):
    """Median duration in ms of each bevy_firefly system, from a chrome trace."""
    events = json.loads(Path(trace_path).read_text())
    if isinstance(events, dict):
        events = events.get("traceEvents", [])
    open_spans, durations = {}, {}
    for e in events:
        name = e.get("name", "")
        if not name.startswith("system") or "bevy_firefly::" not in name:
            continue
        match = re.search(r"bevy_firefly::[\w:]+", name)
        system = match.group(0).removeprefix("bevy_firefly::")
        key = (e.get("tid"), name)
        if e.get("ph") == "X":
            durations.setdefault(system, []).append(e["dur"] / 1000)
        elif e.get("ph") == "B":
            open_spans[key] = e["ts"]
        elif e.get("ph") == "E" and key in open_spans:
            durations.setdefault(system, []).append((e["ts"] - open_spans.pop(key)) / 1000)
    # Skip the first calls, which include pipeline compilation and buffer growth.
    return {s: statistics.median(d[10:] or d) for s, d in durations.items()}


def compare(a, b):
    a = np.asarray(Image.open(a).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(b).convert("RGB"), dtype=np.int16)
    if a.shape != b.shape:
        return None
    delta = np.abs(a - b).max(axis=2)
    return int((delta > 0).sum()), int(delta.max())


def bench_commit(sha, out):
    out.mkdir(parents=True, exist_ok=True)
    run(["git", "checkout", "-q", sha, "--", "src", "Cargo.toml"])
    result = {"sha": sha, "subject": git("log", "-1", "--format=%s", sha), "scenes": {}, "errors": []}

    examples = sorted(set(["bench", *REGRESSION_EXAMPLES]))
    args = [a for e in examples for a in ("--example", e)]
    try:
        run(["cargo", "build", "--release", "--features", FEATURES, *args])
    except subprocess.CalledProcessError:
        result["errors"].append("build failed")
        return result

    for scene in TIMED_SCENES + CHECK_SCENES:
        timed = scene in TIMED_SCENES
        env = {
            "FIREFLY_BENCH_SCENE": scene,
            "FIREFLY_BENCH_OUT": str(out / f"{scene}.json"),
            "FIREFLY_BENCH_SCREENSHOT": str(out / f"bench-{scene}.png"),
            "TRACE_CHROME": str(out / f"trace-{scene}.json"),
        }
        if not timed:
            env |= {"FIREFLY_BENCH_WARMUP": "3", "FIREFLY_BENCH_FRAMES": "3"}
        status, errors = xvfb([TARGET / "bench"], env, out / f"bench-{scene}.log")
        result["errors"] += [f"bench {scene}: {e}" for e in errors[:5]]
        if status != 0:
            result["errors"].append(f"bench {scene} exited with {status}")
            continue
        if timed:
            data = json.loads((out / f"{scene}.json").read_text())
            data["systems_ms"] = system_times(out / f"trace-{scene}.json")
            result["scenes"][scene] = data
        (out / f"trace-{scene}.json").unlink(missing_ok=True)

    for example in REGRESSION_EXAMPLES:
        work = out / f"run-{example}"
        work.mkdir(exist_ok=True)
        status, errors = xvfb(
            [(TARGET / example).resolve()],
            {"CI_TESTING_CONFIG": str(SCREENSHOT_CONFIG), "TRACE_CHROME": str(work / "trace.json")},
            out / f"{example}.log",
            cwd=work,
        )
        result["errors"] += [f"{example}: {e}" for e in errors[:5]]
        if status != 0:
            result["errors"].append(f"{example} exited with {status}")
        for shot in work.glob("screenshot-*.png"):
            shot.rename(out / f"{example}.png")
        shutil.rmtree(work)

    (out / "result.json").write_text(json.dumps(result, indent=2))
    return result


def fmt(value, ref=None):
    if value is None:
        return "–"
    if ref in (None, 0):
        return f"{value:.2f}"
    return f"{value:.2f} ({(value - ref) / ref * 100:+.0f}%)"


def summary(results, out):
    ref, lines = results[0], ["# Firefly benchmark", ""]
    lines.append(f"Reference commit: `{ref['sha'][:8]}` {ref['subject']}")
    lines.append("")
    lines.append("Times are medians in ms. Percentages compare with the reference commit.")

    for scene in TIMED_SCENES:
        lines += ["", f"## {scene}", ""]
        lines.append(
            "| Commit | Frame | Lightmap GPU | Lightmap fragment invocations (M) "
            "| `prepare_data` CPU | All firefly systems CPU |"
        )
        lines.append("|---|---|---|---|---|---|")
        base = ref["scenes"].get(scene, {})

        def metrics(data):
            diag = data.get("diagnostics_median", {})
            systems = data.get("systems_ms", {})
            return [
                data.get("frame_ms_median"),
                diag.get("render/firefly_lightmap/elapsed_gpu"),
                (lambda v: v and v / 1e6)(diag.get("render/firefly_lightmap/fragment_shader_invocations")),
                next((v for k, v in systems.items() if k.endswith("prepare_data")), None),
                sum(systems.values()) if systems else None,
            ]

        for r in results:
            data = r["scenes"].get(scene)
            if data is None:
                lines.append(f"| `{r['sha'][:8]}` {r['subject']} | failed | | | | |")
                continue
            cells = [fmt(v, b) for v, b in zip(metrics(data), metrics(base))]
            lines.append(f"| `{r['sha'][:8]}` {r['subject']} | " + " | ".join(cells) + " |")

    lines += ["", "## Output compared with the reference commit", ""]
    images = sorted(p.name for p in (out / ref["sha"][:8]).glob("*.png"))
    lines.append("| Commit | " + " | ".join(Path(i).stem for i in images) + " |")
    lines.append("|---|" + "---|" * len(images))
    failed = False
    for r in results[1:]:
        cells = []
        for image in images:
            path = out / r["sha"][:8] / image
            if not path.exists():
                cells.append("missing")
                failed = True
                continue
            diff = compare(out / ref["sha"][:8] / image, path)
            if diff is None:
                cells.append("size differs")
                failed = True
            else:
                changed, max_delta = diff
                cells.append("identical" if changed == 0 else f"{changed} px, max Δ {max_delta}")
                failed |= changed > 0
        lines.append(f"| `{r['sha'][:8]}` | " + " | ".join(cells) + " |")

    errors = [e for r in results for e in r["errors"]]
    if errors:
        failed = True
        lines += ["", "## Errors", ""] + [f"- `{e[:300]}`" for e in errors]

    text = "\n".join(lines) + "\n"
    (out / "summary.md").write_text(text)
    print(text)
    return failed


def main():
    base, out = sys.argv[1], Path(sys.argv[2]).resolve()
    commits = git("rev-list", "--reverse", "--first-parent", "--no-merges", f"{base}..HEAD").split()
    # Earlier commits lack the timing spans the bench reads.
    first = git("rev-list", "--reverse", f"{base}..HEAD", "--", ".github/ci/bench.py").split()[0]
    commits = commits[commits.index(first) :]
    results = [bench_commit(sha, out / sha[:8]) for sha in commits]
    run(["git", "checkout", "-q", "HEAD", "--", "src", "Cargo.toml"])
    return 1 if summary(results, out) else 0


if __name__ == "__main__":
    sys.exit(main())
