"""Benchmarks a series of commits and checks that none changes the rendered output.

Runs natively on Windows, macOS and Linux, on whatever GPU the machine has. CI passes `--xvfb`
to render on a virtual display with Mesa's software Vulkan driver instead.

    pip install numpy pillow
    python .github/ci/bench.py main                      # main, then each commit up to HEAD
    python .github/ci/bench.py --commits main HEAD       # just these two
    python .github/ci/bench.py main --scenes lights --rounds 3 --skip-images --out results

The first commit is the reference. With BASE, that's BASE itself if it has this script, or
else the commit that adds it, since earlier commits lack the timing spans the bench reads.

Each commit's `src` and `Cargo.toml` are built with HEAD's examples, in a temporary git
worktree, so uncommitted changes are left alone and aren't benchmarked. The build shares this
checkout's `target` directory.

For each commit this renders the screenshot-only bench scenes and REGRESSION_EXAMPLES. Then it
times the timed scenes for all commits in `--rounds` interleaved rounds, so drift (other apps,
thermal throttling) hits every commit alike, and reports the median and range.

Every later commit's images must match the reference exactly. An image that differs is rendered
twice more, to tell a flaky example from a real change. Results go to OUT/<short sha>/ and a
markdown summary to OUT/summary.md. Keep the windows visible while it runs: some platforms
throttle hidden windows.
"""

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

TIMED_SCENES = ["lights", "tiles", "moving"]
CHECK_SCENES = ["lights_scaled", "lights_fixed", "moving_rotated", "sprites", "sprites_scaled"]
REGRESSION_EXAMPLES = ["simple", "shapes", "crates", "flashlight", "blending", "fov", "render_layers", "test"]
FEATURES = "bevy/bevy_ci_testing,bevy/trace_chrome"
SCREENSHOT_CONFIG = Path(__file__).resolve().parent / "screenshot.ron"
EXE = ".exe" if os.name == "nt" else ""
RETRIES = 2
TIMEOUT_S = 900


class Bench:
    """Settings shared by every run: where the binaries are and how to launch them."""

    def __init__(self, args, worktree, target):
        self.args, self.worktree, self.target = args, worktree, target / "release" / "examples"

    def binary(self, name):
        return self.target / f"{name}{EXE}"

    def launch(self, cmd, env, log, cwd=None):
        """Runs `cmd` with its output in `log`. Returns the exit status and the logged errors."""
        if self.args.xvfb:
            cmd = ["xvfb-run", "-a", "-s", "-screen 0 1280x720x24", *cmd]
        with open(log, "w", encoding="utf-8") as f:
            try:
                status = subprocess.run(
                    list(map(str, cmd)),
                    env={**os.environ, "BEVY_ASSET_ROOT": str(self.worktree), **env},
                    cwd=cwd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    timeout=TIMEOUT_S,
                ).returncode
            except subprocess.TimeoutExpired:
                status = "timeout"
        text = Path(log).read_text(encoding="utf-8", errors="replace")
        errors = [line for line in text.splitlines() if " ERROR " in line or "panicked" in line]
        return status, errors


def run(cmd, **kwargs):
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(list(map(str, cmd)), check=True, **kwargs)


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def system_times(trace_path):
    """Median duration in ms of each bevy_firefly system, from a chrome trace."""
    events = json.loads(Path(trace_path).read_text(encoding="utf-8"))
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


def render_example(bench, example, out):
    work = out / f"run-{example}"
    work.mkdir(exist_ok=True)
    status, errors = bench.launch(
        [bench.binary(example)],
        {"CI_TESTING_CONFIG": str(SCREENSHOT_CONFIG), "TRACE_CHROME": str(work / "trace.json")},
        out / f"{example}.log",
        cwd=work,
    )
    errors = [f"{example}: {e}" for e in errors[:5]]
    if status != 0:
        errors.append(f"{example} exited with {status}")
    for shot in work.glob("screenshot-*.png"):
        shot.replace(out / f"{example}.png")
    shutil.rmtree(work)
    return errors


def bench_commit(bench, sha, out, ref):
    """Builds `sha` and renders its check images. `ref` is the reference commit's dir, if any."""
    out.mkdir(parents=True, exist_ok=True)
    wt = bench.worktree
    # Remove `src` first, so files that `sha` doesn't have aren't left over from another commit.
    shutil.rmtree(wt / "src")
    run(["git", "checkout", "-q", sha, "--", "src", "Cargo.toml"], cwd=wt)
    result = {"sha": sha, "subject": git("log", "-1", "--format=%s", sha), "scenes": {}, "errors": [], "flaky": {}}

    examples = ["bench"] if bench.args.skip_images else sorted({"bench", *REGRESSION_EXAMPLES})
    try:
        run(
            ["cargo", "build", "--release", "--features", FEATURES, *[a for e in examples for a in ("--example", e)]],
            cwd=wt,
            env={**os.environ, "CARGO_TARGET_DIR": str(bench.target.parent.parent)},
        )
    except subprocess.CalledProcessError:
        result["errors"].append("build failed")
        return result
    shutil.copy(bench.binary("bench"), out / f"bench-bin{EXE}")
    if bench.args.skip_images:
        return result

    for scene in CHECK_SCENES:
        env = {
            "FIREFLY_BENCH_SCENE": scene,
            "FIREFLY_BENCH_OUT": str(out / f"{scene}.json"),
            "FIREFLY_BENCH_SCREENSHOT": str(out / f"bench-{scene}.png"),
            "FIREFLY_BENCH_WARMUP": "3",
            "FIREFLY_BENCH_FRAMES": "3",
        }
        status, errors = bench.launch([out / f"bench-bin{EXE}"], env, out / f"bench-{scene}.log")
        result["errors"] += [f"bench {scene}: {e}" for e in errors[:5]]
        if status != 0:
            result["errors"].append(f"bench {scene} exited with {status}")

    for example in REGRESSION_EXAMPLES:
        result["errors"] += render_example(bench, example, out)
        image, ref_image = out / f"{example}.png", ref and ref / f"{example}.png"
        if not (ref_image and ref_image.exists() and image.exists()) or compare(ref_image, image) == (0, 0):
            continue
        # Render again: if a retry matches, the example is nondeterministic, not changed.
        first = image.with_suffix(".first.png")
        image.replace(first)
        diffs = []
        for _ in range(RETRIES):
            render_example(bench, example, out)
            diffs.append(image.exists() and compare(ref_image, image) != (0, 0))
        if not all(diffs):
            result["flaky"][example] = f"{sum(diffs) + 1}/{RETRIES + 1} renders differ"
        else:
            first.replace(image)
        first.unlink(missing_ok=True)

    return result


def time_commits(bench, results, out):
    """Runs every timed scene for every built commit, `--rounds` times, alternating commits."""
    rounds = {}
    for r in range(bench.args.rounds):
        for res in results:
            dir = out / res["sha"][:8]
            binary = dir / f"bench-bin{EXE}"
            if not binary.exists():
                continue
            for scene in bench.args.scenes:
                print(f"round {r + 1}/{bench.args.rounds}: {res['sha'][:8]} {scene}", flush=True)
                env = {
                    "FIREFLY_BENCH_SCENE": scene,
                    "FIREFLY_BENCH_OUT": str(dir / f"{scene}.json"),
                    "FIREFLY_BENCH_SCREENSHOT": str(dir / (f"bench-{scene}.png" if r == 0 else "discard.png")),
                    "TRACE_CHROME": str(dir / f"trace-{scene}.json"),
                }
                status, errors = bench.launch([binary], env, dir / f"bench-{scene}.log")
                if r == 0:
                    res["errors"] += [f"bench {scene}: {e}" for e in errors[:5]]
                if status != 0:
                    res["errors"].append(f"bench {scene} round {r} exited with {status}")
                    continue
                data = json.loads((dir / f"{scene}.json").read_text(encoding="utf-8"))
                diag = data.get("diagnostics_median", {})
                systems = system_times(dir / f"trace-{scene}.json")
                (dir / f"trace-{scene}.json").unlink(missing_ok=True)
                for key, value in metrics(data["frame_ms_median"], diag, systems).items():
                    rounds.setdefault((res["sha"], scene, key), []).append(value)
    for res in results:
        for name in ("discard.png", f"bench-bin{EXE}"):
            (out / res["sha"][:8] / name).unlink(missing_ok=True)
        for scene in bench.args.scenes:
            values = {k: rounds.get((res["sha"], scene, k)) for k in METRICS}
            if values["frame"]:
                res["scenes"][scene] = values
        (out / res["sha"][:8] / "result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")


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


def summary(bench, results, out):
    ref, lines = results[0], ["# Firefly benchmark", ""]
    lines.append(f"Reference commit: `{ref['sha'][:8]}` {ref['subject']}")
    lines.append("")
    lines.append(
        f"Medians in ms over {bench.args.rounds} rounds. Percentages compare each commit with the one before it; "
        "`~` means the two commits' ranges overlap, so the change is within noise. "
        "Frame range is min–max across rounds."
    )

    for scene in bench.args.scenes:
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
    (out / "summary.md").write_text(text, encoding="utf-8")
    print(text)
    return failed


def resolve(ref):
    sha = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"], capture_output=True, text=True)
    if sha.returncode != 0:
        sys.exit(f"{ref!r} isn't a commit here. Fetch it, or use origin/{ref}.")
    return sha.stdout.strip()


def commits_to_bench(args):
    if args.commits:
        return [resolve(c) for c in args.commits]
    if not args.base:
        sys.exit("give BASE or --commits")
    base = resolve(args.base)
    commits = git("rev-list", "--reverse", "--first-parent", "--no-merges", f"{base}..HEAD").split()
    has_script = subprocess.run(["git", "cat-file", "-e", f"{base}:.github/ci/bench.py"], capture_output=True)
    if has_script.returncode == 0:
        return [base, *commits]
    first = git("rev-list", "--reverse", f"{base}..HEAD", "--", ".github/ci/bench.py").split()[0]
    return commits[commits.index(first) :]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base", nargs="?", help="benchmark the commits after this one, up to HEAD")
    parser.add_argument("out_dir", nargs="?", metavar="OUT", help="results directory, same as --out")
    parser.add_argument("--out", help="results directory (default bench-results)")
    parser.add_argument("--commits", nargs="+", metavar="REF", help="benchmark these commits instead of BASE..HEAD")
    parser.add_argument("--rounds", type=int, default=5, help="timing rounds per commit (default 5)")
    parser.add_argument("--scenes", nargs="+", default=TIMED_SCENES, choices=TIMED_SCENES, help="timed scenes")
    parser.add_argument("--skip-images", action="store_true", help="only time; skip the image checks")
    parser.add_argument("--xvfb", action="store_true", help="run on a virtual X display (Linux CI)")
    args = parser.parse_args()
    if args.commits and args.base:
        parser.error("give either BASE or --commits, not both")
    if args.xvfb and not shutil.which("xvfb-run"):
        parser.error("--xvfb needs xvfb-run (apt install xvfb)")
    sys.stdout.reconfigure(encoding="utf-8")

    commits = commits_to_bench(args)
    root = Path(git("rev-parse", "--show-toplevel"))
    out = Path(args.out or args.out_dir or "bench-results").resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = Path(os.environ.get("CARGO_TARGET_DIR", root / "target")).resolve()
    worktree = Path(tempfile.mkdtemp(prefix="firefly-bench-")) / "repo"
    run(["git", "worktree", "add", "-q", "--detach", worktree, "HEAD"])
    try:
        bench = Bench(args, worktree, target)
        results = []
        for sha in commits:
            results.append(bench_commit(bench, sha, out / sha[:8], results and out / results[0]["sha"][:8]))
        time_commits(bench, results, out)
    finally:
        run(["git", "worktree", "remove", "--force", worktree])
        shutil.rmtree(worktree.parent, ignore_errors=True)
    return 1 if summary(bench, results, out) else 0


if __name__ == "__main__":
    sys.exit(main())
