# Firefly benchmark

Reference commit: `a9be26a4` Add deterministic bench scenes, GPU pass timings and a per-commit CI benchmark

Medians in ms over 5 rounds. Percentages compare each commit with the one before it; `~` means the two commits' ranges overlap, so the change is within noise. Frame range is min–max across rounds.

## lights

| Commit | Frame | Frame range | Lightmap GPU | Lightmap fragment invocations (M) | `prepare_data` CPU | All firefly systems CPU |
|---|---|---|---|---|---|---|
| `a9be26a4` Add deterministic bench scenes, GPU pass timings and a per-commit CI benchmark | 1903.66 | 1898–1906 | 1860.24 | 368.64 | 17.46 | 18.00 |
| `6273c942` Draw each light as a quad over its bounds and skip texture reads outside its range | 149.59 (-92%) | 146–150 | 105.28 (-94%) | 9.44 (-97%) | 19.09 (+9%) | 19.52 (+8%) |
| `4a7c80d8` Pass the light index as the instance index instead of a per-light buffer | 147.07 (-2% ~) | 145–149 | 111.28 (+6%) | 9.44 (+0% ~) | 13.19 (-31%) | 13.65 (-30%) |
| `45322b40` Merge every light's bins into one buffer per view, with one bind group per view | 139.85 (-5%) | 138–141 | 112.51 (+1%) | 9.44 (+0% ~) | 5.33 (-60%) | 5.75 (-58%) |
| `fcf9ef38` Find each light's occluders with a uniform grid instead of testing every occluder | 136.61 (-2% ~) | 133–138 | 112.38 (-0% ~) | 9.44 (+0% ~) | 2.45 (-54%) | 2.85 (-50%) |
| `f1bbb4e0` Tonemap each light's color once in the vertex shader instead of per pixel | 131.92 (-3% ~) | 127–134 | 108.28 (-4%) | 9.44 (+0% ~) | 2.41 (-1% ~) | 2.82 (-1% ~) |
| `acadfaa9` Reuse a light's bins when neither it, its views nor nearby occluders changed | 131.26 (-0% ~) | 128–133 | 108.20 (-0% ~) | 9.44 (+0% ~) | 0.84 (-65%) | 1.25 (-56%) |
| `a33f1a9f` Load each light once per pixel and skip stencil and normal reads that aren't used | 106.46 (-19%) | 104–109 | 84.63 (-22%) | 9.44 (+0% ~) | 0.77 (-8% ~) | 1.17 (-6% ~) |
| `e19c504c` Draw all of a view's lights in one instanced draw, and keep per-view and config buffers | 105.61 (-1% ~) | 103–109 | 84.52 (-0% ~) | 9.44 (+0% ~) | 0.67 (-13% ~) | 0.94 (-20% ~) |
| `fcf04fed` Rebuild all bins when occluders change order, and keep inverted bounds in the grid | 103.33 (-2% ~) | 103–108 | 84.44 (-0% ~) | 9.44 (+0% ~) | 0.57 (-14% ~) | 0.79 (-15% ~) |
| `30738a7b` Remove dead code and commented-out debug lines, and trim comments | 103.69 (+0% ~) | 103–108 | 84.41 (-0% ~) | 9.44 (+0% ~) | 0.55 (-5% ~) | 0.78 (-1% ~) |
| `8807c619` Time every commit over five interleaved rounds and retry differing images | 104.78 (+1% ~) | 102–108 | 84.46 (+0% ~) | 9.44 (+0% ~) | 0.64 (+18% ~) | 0.90 (+14% ~) |
| `a53539ee` Run the commit benchmark natively on Windows, macOS and Linux | 105.24 (+0% ~) | 102–106 | 84.48 (+0% ~) | 9.44 (+0% ~) | 0.70 (+8% ~) | 0.99 (+11% ~) |
| **Total, last vs reference** | 105.24 (-94%) |  | 84.48 (-95%) | 9.44 (-97%) | 0.70 (-96%) | 0.99 (-94%) |

## tiles

| Commit | Frame | Frame range | Lightmap GPU | Lightmap fragment invocations (M) | `prepare_data` CPU | All firefly systems CPU |
|---|---|---|---|---|---|---|
| `a9be26a4` Add deterministic bench scenes, GPU pass timings and a per-commit CI benchmark | 250.94 | 247–252 | 215.05 | 36.86 | 13.02 | 13.62 |
| `6273c942` Draw each light as a quad over its bounds and skip texture reads outside its range | 93.51 (-63%) | 91–96 | 60.96 (-72%) | 5.06 (-86%) | 12.97 (-0% ~) | 13.55 (-0% ~) |
| `4a7c80d8` Pass the light index as the instance index instead of a per-light buffer | 97.69 (+4% ~) | 96–99 | 64.65 (+6%) | 5.06 (+0% ~) | 12.85 (-1% ~) | 13.39 (-1% ~) |
| `45322b40` Merge every light's bins into one buffer per view, with one bind group per view | 99.55 (+2% ~) | 98–101 | 66.00 (+2%) | 5.06 (+0% ~) | 13.56 (+5% ~) | 14.12 (+5% ~) |
| `fcf9ef38` Find each light's occluders with a uniform grid instead of testing every occluder | 94.81 (-5% ~) | 89–113 | 66.32 (+0% ~) | 5.06 (+0% ~) | 6.62 (-51%) | 7.16 (-49%) |
| `f1bbb4e0` Tonemap each light's color once in the vertex shader instead of per pixel | 90.22 (-5% ~) | 87–93 | 63.82 (-4%) | 5.06 (+0% ~) | 6.59 (-0% ~) | 7.10 (-1% ~) |
| `acadfaa9` Reuse a light's bins when neither it, its views nor nearby occluders changed | 85.42 (-5% ~) | 84–88 | 63.79 (-0% ~) | 5.06 (+0% ~) | 1.51 (-77%) | 1.99 (-72%) |
| `a33f1a9f` Load each light once per pixel and skip stencil and normal reads that aren't used | 71.92 (-16%) | 71–74 | 50.72 (-20%) | 5.06 (+0% ~) | 1.63 (+8% ~) | 2.13 (+7% ~) |
| `e19c504c` Draw all of a view's lights in one instanced draw, and keep per-view and config buffers | 69.77 (-3% ~) | 70–75 | 50.67 (-0% ~) | 5.06 (+0% ~) | 1.31 (-20% ~) | 1.77 (-17% ~) |
| `fcf04fed` Rebuild all bins when occluders change order, and keep inverted bounds in the grid | 69.97 (+0% ~) | 70–75 | 50.69 (+0% ~) | 5.06 (+0% ~) | 1.35 (+3% ~) | 1.77 (-0% ~) |
| `30738a7b` Remove dead code and commented-out debug lines, and trim comments | 70.12 (+0% ~) | 69–74 | 50.69 (+0% ~) | 5.06 (+0% ~) | 1.39 (+2% ~) | 1.83 (+4% ~) |
| `8807c619` Time every commit over five interleaved rounds and retry differing images | 71.44 (+2% ~) | 69–73 | 50.70 (+0% ~) | 5.06 (+0% ~) | 1.58 (+14% ~) | 2.07 (+13% ~) |
| `a53539ee` Run the commit benchmark natively on Windows, macOS and Linux | 72.45 (+1% ~) | 69–73 | 50.70 (-0% ~) | 5.06 (+0% ~) | 1.54 (-2% ~) | 2.08 (+0% ~) |
| **Total, last vs reference** | 72.45 (-71%) |  | 50.70 (-76%) | 5.06 (-86%) | 1.54 (-88%) | 2.08 (-85%) |

## moving

| Commit | Frame | Frame range | Lightmap GPU | Lightmap fragment invocations (M) | `prepare_data` CPU | All firefly systems CPU |
|---|---|---|---|---|---|---|
| `a9be26a4` Add deterministic bench scenes, GPU pass timings and a per-commit CI benchmark | 863.47 | 863–865 | 830.10 | 138.24 | 8.37 | 9.73 |
| `6273c942` Draw each light as a quad over its bounds and skip texture reads outside its range | 255.66 (-70%) | 253–258 | 222.19 (-73%) | 13.82 (-90%) | 8.48 (+1% ~) | 10.09 (+4% ~) |
| `4a7c80d8` Pass the light index as the instance index instead of a per-light buffer | 263.82 (+3%) | 263–265 | 231.28 (+4%) | 13.82 (-0% ~) | 8.01 (-6% ~) | 9.29 (-8%) |
| `45322b40` Merge every light's bins into one buffer per view, with one bind group per view | 263.81 (-0% ~) | 263–319 | 235.38 (+2%) | 13.82 (+0% ~) | 5.94 (-26%) | 6.63 (-29%) |
| `fcf9ef38` Find each light's occluders with a uniform grid instead of testing every occluder | 262.49 (-1%) | 256–263 | 235.63 (+0% ~) | 13.82 (+0% ~) | 3.54 (-40%) | 4.19 (-37%) |
| `f1bbb4e0` Tonemap each light's color once in the vertex shader instead of per pixel | 255.61 (-3%) | 250–256 | 228.65 (-3%) | 13.82 (+0% ~) | 3.49 (-1% ~) | 4.18 (-0% ~) |
| `acadfaa9` Reuse a light's bins when neither it, its views nor nearby occluders changed | 256.23 (+0% ~) | 251–257 | 229.05 (+0% ~) | 13.82 (+0% ~) | 2.73 (-22% ~) | 3.45 (-17% ~) |
| `a33f1a9f` Load each light once per pixel and skip stencil and normal reads that aren't used | 219.77 (-14%) | 218–222 | 194.35 (-15%) | 13.82 (+0% ~) | 2.58 (-5% ~) | 3.21 (-7% ~) |
| `e19c504c` Draw all of a view's lights in one instanced draw, and keep per-view and config buffers | 218.86 (-0% ~) | 217–273 | 194.51 (+0% ~) | 13.82 (+0% ~) | 2.61 (+1% ~) | 3.21 (-0% ~) |
| `fcf04fed` Rebuild all bins when occluders change order, and keep inverted bounds in the grid | 216.38 (-1% ~) | 215–222 | 194.41 (-0% ~) | 13.82 (+0% ~) | 2.45 (-6% ~) | 2.97 (-7% ~) |
| `30738a7b` Remove dead code and commented-out debug lines, and trim comments | 217.81 (+1% ~) | 215–221 | 194.34 (-0% ~) | 13.82 (-0% ~) | 2.55 (+4% ~) | 3.09 (+4% ~) |
| `8807c619` Time every commit over five interleaved rounds and retry differing images | 219.59 (+1% ~) | 214–220 | 194.34 (-0% ~) | 13.82 (+0% ~) | 2.72 (+7% ~) | 3.32 (+7% ~) |
| `a53539ee` Run the commit benchmark natively on Windows, macOS and Linux | 220.40 (+0% ~) | 215–271 | 194.78 (+0% ~) | 13.82 (+0% ~) | 2.68 (-2% ~) | 3.31 (-0% ~) |
| **Total, last vs reference** | 220.40 (-74%) |  | 194.78 (-77%) | 13.82 (-90%) | 2.68 (-68%) | 3.31 (-66%) |

## Output compared with the reference commit

| Commit | bench-lights | bench-lights_fixed | bench-lights_scaled | bench-moving | bench-moving_rotated | bench-sprites | bench-sprites_scaled | bench-tiles | blending | crates | flashlight | fov | render_layers | shapes | simple | test |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `6273c942` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
| `4a7c80d8` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
| `45322b40` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
| `fcf9ef38` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
| `f1bbb4e0` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
| `acadfaa9` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
| `a33f1a9f` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
| `e19c504c` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
| `fcf04fed` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
| `30738a7b` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
| `8807c619` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
| `a53539ee` | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical | identical |
