"""Benchmarks every commit of a pull request and checks that none changes the rendered output.

Usage: bench.py BASE_SHA OUT_DIR

For each commit after BASE_SHA, starting at the one that adds this script, this builds that commit's `src` with this checkout's examples,
then renders the screenshot-only bench scenes and the examples in REGRESSION_EXAMPLES.
After every commit is built, it runs the timed bench scenes for all commits in BENCH_ROUNDS
interleaved rounds, so runner drift hits every commit alike, and reports the median and range.

The first commit is the reference: every later commit's images must match it exactly.
An image that differs is rendered twice more, to tell a flaky example from a real change.
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
ROUNDS = int(os.environ.get("BENCH_ROUNDS", "5"))
RETRIES = 2


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


def render_example(example, out):
    work = out / f"run-{example}"
    work.mkdir(exist_ok=True)
    status, errors = xvfb(
        [(TARGET / example).resolve()],
        {"CI_TESTING_CONFIG": str(SCREENSHOT_CONFIG), "TRACE_CHROME": str(work / "trace.json")},
        out / f"{example}.log",
        cwd=work,
    )
    errors = [f"{example}: {e}" for e in errors[:5]]
    if status != 0:
        errors.append(f"{example} exited with {status}")
    for shot in work.glob("screenshot-*.png"):
        shot.rename(out / f"{example}.png")
    shutil.rmtree(work)
    return errors


def bench_commit(sha, out, ref):
    """Builds `sha` and renders its check images. `ref` is the reference commit's dir, if any."""
    out.mkdir(parents=True, exist_ok=True)
    run(["git", "checkout", "-q", sha, "--", "src", "Cargo.toml"])
    result = {"sha": sha, "subject": git("log", "-1", "--format=%s", sha), "scenes": {}, "errors": [], "flaky": {}}

    examples = sorted(set(["bench", *REGRESSION_EXAMPLES]))
    args = [a for e in examples for a in ("--example", e)]
    try:
        run(["cargo", "build", "--release", "--features", FEATURES, *args])
    except subprocess.CalledProcessError:
        result["errors"].append("build failed")
        return result
    shutil.copy(TARGET / "bench", out / "bench-bin")

    for scene in CHECK_SCENES:
        env = {
            "FIREFLY_BENCH_SCENE": scene,
            "FIREFLY_BENCH_OUT": str(out / f"{scene}.json"),
            "FIREFLY_BENCH_SCREENSHOT": str(out / f"bench-{scene}.png"),
            "FIREFLY_BENCH_WARMUP": "3",
            "FIREFLY_BENCH_FRAMES": "3",
        }
        status, errors = xvfb([out / "bench-bin"], env, out / f"bench-{scene}.log")
        result["errors"] += [f"bench {scene}: {e}" for e in errors[:5]]
        if status != 0:
            result["errors"].append(f"bench {scene} exited with {status}")

    for example in REGRESSION_EXAMPLES:
        result["errors"] += render_example(example, out)
        image, ref_image = out / f"{example}.png", ref and ref / f"{example}.png"
        if not (ref_image and ref_image.exists() and image.exists()) or compare(ref_image, image) == (0, 0):
            continue
        # Render again: if a retry matches, the example is nondeterministic, not changed.
        first = image.with_suffix(".first.png")
        image.rename(first)
        diffs = []
        for _ in range(RETRIES):
            render_example(example, out)
            diffs.append(image.exists() and compare(ref_image, image) != (0, 0))
        if not all(diffs):
            result["flaky"][example] = f"{sum(diffs) + 1}/{RETRIES + 1} renders differ"
        else:
            first.replace(image)
        first.unlink(missing_ok=True)

    return result


def time_commits(results, out):
    """Runs every timed scene for every built commit, ROUNDS times, alternating commits."""
    rounds = {}
    for r in range(ROUNDS):
        for res in results:
            dir = out / res["sha"][:8]
            if not (dir / "bench-bin").exists():
                continue
            for scene in TIMED_SCENES:
                env = {
                    "FIREFLY_BENCH_SCENE": scene,
                    "FIREFLY_BENCH_OUT": str(dir / f"{scene}.json"),
                    "FIREFLY_BENCH_SCREENSHOT": str(dir / (f"bench-{scene}.png" if r == 0 else "discard.png")),
                    "TRACE_CHROME": str(dir / f"trace-{scene}.json"),
                }
                status, errors = xvfb([dir / "bench-bin"], env, dir / f"bench-{scene}.log")
                if r == 0:
                    res["errors"] += [f"bench {scene}: {e}" for e in errors[:5]]
                if status != 0:
                    res["errors"].append(f"bench {scene} round {r} exited with {status}")
                    continue
                data = json.loads((dir / f"{scene}.json").read_text())
                diag = data.get("diagnostics_median", {})
                systems = system_times(dir / f"trace-{scene}.json")
                (dir / f"trace-{scene}.json").unlink(missing_ok=True)
                for key, value in metrics(data["frame_ms_median"], diag, systems).items():
                    rounds.setdefault((res["sha"], scene, key), []).append(value)
    for res in results:
        for name in ("discard.png", "bench-bin"):
            (out / res["sha"][:8] / name).unlink(missing_ok=True)
        for scene in TIMED_SCENES:
            values = {k: rounds.get((res["sha"], scene, k)) for k in METRICS}
            if values["frame"]:
                res["scenes"][scene] = values
        (out / res["sha"][:8] / "result.json").write_text(json.dumps(res, indent=2))


METRICS = ["frame", "gpu", "invocations", "prepare_data", "systems"]


def metrics(frame, diag, systems):
    invocations = diag.get("render/firefly_lightmap/fragment_shader_invocations")
    return {
        "frame": frame,
        "gpu": diag.get("render/firefly_lightmap/elapsed_gpu"),
        "invocations": invocations and invocations / 1e6,
        "prepare_data": next((v for k, v in systems.items() if k.endswith("prepare_data")), None),
        "systems": sum(systems.values()) if systems else None,
    }


def cell(values, prev):
    """Median, then the change from the previous commit. `~` marks a change within run-to-run
    spread: the two commits' ranges across rounds overlap."""
    values = [v for v in values or [] if v is not None]
    if not values:
        return "–"
    med = statistics.median(values)
    text = f"{med:.2f}"
    prev = [v for v in prev or [] if v is not None]
    if prev and statistics.median(prev):
        p = statistics.median(prev)
        noise = len(values) > 1 and min(values) <= max(prev) and min(prev) <= max(values)
        text += f" ({(med - p) / p * 100:+.0f}%{' ~' if noise else ''})"
    return text


def summary(results, out):
    ref, lines = results[0], ["# Firefly benchmark", ""]
    lines.append(f"Reference commit: `{ref['sha'][:8]}` {ref['subject']}")
    lines.append("")
    lines.append(
        f"Medians in ms over {ROUNDS} rounds. Percentages compare each commit with the one before it; "
        "`~` means the two commits' ranges overlap, so the change is within noise. "
        "Frame range is min–max across rounds."
    )

    for scene in TIMED_SCENES:
        lines += ["", f"## {scene}", ""]
        lines.append(
            "| Commit | Frame | Frame range | Lightmap GPU | Lightmap fragment invocations (M) "
            "| `prepare_data` CPU | All firefly systems CPU |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        prev = None
        for r in results:
            data = r["scenes"].get(scene)
            if data is None:
                lines.append(f"| `{r['sha'][:8]}` {r['subject']} | failed | | | | | |")
                continue
            cells = [cell(data[k], prev and prev[k]) for k in METRICS]
            frames = data["frame"]
            cells.insert(1, f"{min(frames):.0f}–{max(frames):.0f}")
            lines.append(f"| `{r['sha'][:8]}` {r['subject']} | " + " | ".join(cells) + " |")
            prev = data
        first, last = ref["scenes"].get(scene), results[-1]["scenes"].get(scene)
        if first and last and first is not last:
            total = [cell(last[k], first[k]) for k in METRICS]
            total.insert(1, "")
            lines.append("| **Total, last vs reference** | " + " | ".join(total) + " |")

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

    flaky = [f"{r['sha'][:8]} {ex}: {why}" for r in results for ex, why in r["flaky"].items()]
    if flaky:
        lines += ["", "## Flaky examples", "", "A retry matched the reference, so these don't fail the run.", ""]
        lines += [f"- {f}" for f in flaky]

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
    results = []
    for sha in commits:
        results.append(bench_commit(sha, out / sha[:8], results and out / results[0]["sha"][:8]))
    run(["git", "checkout", "-q", "HEAD", "--", "src", "Cargo.toml"])
    time_commits(results, out)
    return 1 if summary(results, out) else 0


if __name__ == "__main__":
    sys.exit(main())
