//! Deterministic benchmark scenes, used by CI to time changes.
//!
//! Set `FIREFLY_BENCH_SCENE` to one of the names in [`Scene::from_name`].
//! Everything moves by frame count, not time, so every run renders the same frames.
//!
//! Optional variables:
//! - `FIREFLY_BENCH_WARMUP`: frames skipped before timing (default 10)
//! - `FIREFLY_BENCH_FRAMES`: frames timed (default 30)
//! - `FIREFLY_BENCH_OUT`: JSON results path (default `bench.json`)
//! - `FIREFLY_BENCH_SCREENSHOT`: screenshot path, taken after the last timed frame (default `bench.png`)

use std::{env, f32::consts::TAU, time::Instant};

use bevy::{
    color::palettes::css::{BLUE, GREEN, LIME, ORANGE, PURPLE, RED, TEAL, YELLOW},
    diagnostic::DiagnosticsStore,
    platform::collections::HashMap,
    prelude::*,
    render::{
        RenderPlugin,
        diagnostic::RenderDiagnosticsPlugin,
        view::screenshot::{Screenshot, save_to_disk},
    },
    window::{PresentMode, WindowResolution},
};
use bevy_firefly::{data::NormalMode, prelude::*};
use rand::{Rng, SeedableRng, rngs::StdRng};

const WIDTH: f32 = 1280.0;
const HEIGHT: f32 = 720.0;
const COLORS: [Srgba; 8] = [BLUE, GREEN, LIME, ORANGE, PURPLE, RED, TEAL, YELLOW];

#[derive(Resource, Clone, Copy, PartialEq)]
enum Scene {
    /// Many small lights, few occluders. Stresses per-light pixel cost.
    Lights,
    /// A few large lights over a dense tile grid. Stresses shadow setup.
    Tiles,
    /// Lights and occluders that all move every frame.
    Moving,
    /// Normal-mapped sprites with z-sorted shadows.
    Sprites,
}

#[derive(Resource, Clone, Copy)]
struct Variant {
    lightmap_size: LightmapSize,
    camera_rotation: f32,
    camera_scale: f32,
}

impl Scene {
    fn from_name(name: &str) -> (Scene, Variant) {
        let mut variant = Variant {
            lightmap_size: LightmapSize::Window,
            camera_rotation: 0.0,
            camera_scale: 1.0,
        };
        let scene = match name {
            "lights" => Scene::Lights,
            "lights_scaled" => {
                variant.lightmap_size = LightmapSize::Scaled(0.5);
                Scene::Lights
            }
            "lights_fixed" => {
                variant.lightmap_size = LightmapSize::Fixed(uvec2(800, 450));
                Scene::Lights
            }
            "tiles" => {
                variant.camera_scale = 2.0;
                Scene::Tiles
            }
            "moving" => Scene::Moving,
            "moving_rotated" => {
                variant.camera_rotation = 0.4;
                variant.camera_scale = 1.5;
                Scene::Moving
            }
            "sprites" => {
                variant.camera_scale = 0.25;
                Scene::Sprites
            }
            "sprites_scaled" => {
                variant.camera_scale = 0.25;
                variant.lightmap_size = LightmapSize::Scaled(0.5);
                Scene::Sprites
            }
            _ => panic!("unknown FIREFLY_BENCH_SCENE {name:?}"),
        };
        (scene, variant)
    }
}

#[derive(Resource)]
struct Bench {
    name: String,
    warmup: u32,
    frames: u32,
    out: String,
    screenshot: String,
    frame: u32,
    last: Option<Instant>,
    frame_ms: Vec<f64>,
    diagnostics: HashMap<String, Vec<f64>>,
}

fn env_or<T: std::str::FromStr>(key: &str, default: T) -> T {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn main() {
    let name = env::var("FIREFLY_BENCH_SCENE").unwrap_or_else(|_| "lights".into());
    let (scene, variant) = Scene::from_name(&name);

    let bench = Bench {
        name,
        warmup: env_or("FIREFLY_BENCH_WARMUP", 10),
        frames: env_or("FIREFLY_BENCH_FRAMES", 30),
        out: env_or("FIREFLY_BENCH_OUT", "bench.json".to_string()),
        screenshot: env_or("FIREFLY_BENCH_SCREENSHOT", "bench.png".to_string()),
        frame: 0,
        last: None,
        frame_ms: vec![],
        diagnostics: default(),
    };

    App::new()
        .add_plugins((
            DefaultPlugins
                .set(WindowPlugin {
                    primary_window: Some(Window {
                        resolution: WindowResolution::new(WIDTH as u32, HEIGHT as u32)
                            .with_scale_factor_override(1.0),
                        present_mode: PresentMode::AutoNoVsync,
                        resizable: false,
                        ..default()
                    }),
                    ..default()
                })
                // Otherwise the first frames can render before the shaders are ready.
                .set(RenderPlugin {
                    synchronous_pipeline_compilation: true,
                    ..default()
                })
                .set(ImagePlugin::default_nearest()),
            FireflyPlugin,
            RenderDiagnosticsPlugin,
        ))
        .insert_resource(scene)
        .insert_resource(variant)
        .insert_resource(bench)
        .add_systems(Startup, setup)
        .add_systems(Update, animate)
        .add_systems(Last, record)
        .run();
}

#[derive(Component)]
struct Orbit {
    center: Vec2,
    radius: f32,
    phase: f32,
    speed: f32,
    spin: f32,
}

/// Assets the scene waits for before it starts counting frames.
#[derive(Resource, Default)]
struct Loading(Vec<UntypedHandle>);

fn setup(
    mut commands: Commands,
    scene: Res<Scene>,
    variant: Res<Variant>,
    asset_server: Res<AssetServer>,
) {
    let mut rng = StdRng::seed_from_u64(7);
    let mut proj = OrthographicProjection::default_2d();
    proj.scale = variant.camera_scale;

    commands.spawn((
        Camera2d,
        Projection::Orthographic(proj),
        Transform::from_rotation(Quat::from_rotation_z(variant.camera_rotation)),
        FireflyConfig {
            ambient_color: Color::WHITE,
            ambient_brightness: 0.1,
            soft_shadows: true,
            lightmap_size: variant.lightmap_size,
            z_sorting: *scene == Scene::Sprites,
            normal_mode: if *scene == Scene::Sprites {
                NormalMode::TopDownY
            } else {
                NormalMode::None
            },
            ..default()
        },
    ));

    let half = vec2(WIDTH, HEIGHT) * variant.camera_scale / 2.0;
    let random_pos = |rng: &mut StdRng, margin: f32| {
        vec2(
            rng.random_range(-half.x + margin..half.x - margin),
            rng.random_range(-half.y + margin..half.y - margin),
        )
    };
    let color = |rng: &mut StdRng| Color::Srgba(COLORS[rng.random_range(0..COLORS.len())]);

    let (n_lights, radius, n_occluders) = match *scene {
        Scene::Lights => (400, 30.0..120.0, 120),
        Scene::Tiles => (40, 200.0..600.0, 0),
        Scene::Moving => (150, 60.0..250.0, 250),
        Scene::Sprites => (6, 30.0..90.0, 0),
    };

    for _ in 0..n_lights {
        let pos = random_pos(&mut rng, 0.0);
        let mut light = commands.spawn((
            PointLight2d {
                color: color(&mut rng),
                intensity: rng.random_range(0.5..1.5),
                radius: rng.random_range(radius.clone()),
                ..default()
            },
            Transform::from_translation(pos.extend(0.0)),
        ));
        if *scene == Scene::Moving {
            light.insert(Orbit {
                center: pos,
                radius: rng.random_range(10.0..60.0),
                phase: rng.random_range(0.0..TAU),
                speed: rng.random_range(0.01..0.05),
                spin: 0.0,
            });
        }
    }

    for i in 0..n_occluders {
        let pos = random_pos(&mut rng, 20.0);
        let occluder = match i % 4 {
            0 => Occluder2d::circle(rng.random_range(6.0..16.0)),
            1 => Occluder2d::round_rectangle(
                rng.random_range(4.0..20.0),
                rng.random_range(4.0..20.0),
                rng.random_range(2.0..6.0),
            ),
            2 => Occluder2d::polygon(vec![vec2(-12., -8.), vec2(0., 14.), vec2(12., -8.)]).unwrap(),
            _ => Occluder2d::polyline(vec![
                vec2(-20., -3.),
                vec2(-8., 5.),
                vec2(4., -4.),
                vec2(18., 4.),
            ])
            .unwrap(),
        };
        let occluder = if i % 7 == 0 {
            occluder.with_color(color(&mut rng)).with_opacity(0.6)
        } else {
            occluder
        };
        let mut entity = commands.spawn((occluder, Transform::from_translation(pos.extend(0.0))));
        if *scene == Scene::Moving {
            entity.insert(Orbit {
                center: pos,
                radius: rng.random_range(5.0..40.0),
                phase: rng.random_range(0.0..TAU),
                speed: rng.random_range(0.01..0.04),
                spin: rng.random_range(-0.05..0.05),
            });
        }
    }

    if *scene == Scene::Sprites {
        let image = asset_server.load("crate.png");
        let normal = NormalMap::from_file("crate_normal.png", &asset_server).handle();
        commands.insert_resource(Loading(vec![
            image.clone().untyped(),
            normal.clone().untyped(),
        ]));
        for x in -4..=4 {
            for y in -2..=2 {
                let pos = vec2(x as f32 * 30.0, y as f32 * 25.0);
                commands.spawn((
                    Sprite::from_image(image.clone()),
                    NormalMap::from_image(normal.clone()),
                    Transform::from_translation(pos.extend(-pos.y)),
                    Occluder2d::rectangle(12.0, 5.0),
                ));
            }
        }
    }

    if *scene == Scene::Tiles {
        // A grid of 16x16 tiles, about 60% filled, with a few rooms carved out.
        let step = 24.0;
        let (nx, ny) = ((2.0 * half.x / step) as i32, (2.0 * half.y / step) as i32);
        for x in 0..nx {
            for y in 0..ny {
                if rng.random_bool(0.4) || (x % 12 < 4 && y % 9 < 3) {
                    continue;
                }
                let pos = vec2(x as f32 * step - half.x, y as f32 * step - half.y);
                commands.spawn((
                    Occluder2d::rectangle(16.0, 16.0),
                    Transform::from_translation(pos.extend(0.0)),
                ));
            }
        }
    }
}

fn animate(bench: Res<Bench>, mut orbits: Query<(&Orbit, &mut Transform)>) {
    let t = bench.frame as f32;
    for (orbit, mut transform) in &mut orbits {
        let angle = orbit.phase + t * orbit.speed;
        let pos = orbit.center + Vec2::from_angle(angle) * orbit.radius;
        transform.translation = pos.extend(0.0);
        transform.rotation = Quat::from_rotation_z(orbit.phase + t * orbit.spin);
    }
}

fn record(
    mut commands: Commands,
    mut bench: ResMut<Bench>,
    store: Res<DiagnosticsStore>,
    loading: Option<Res<Loading>>,
    asset_server: Res<AssetServer>,
    mut exit: MessageWriter<AppExit>,
) {
    if let Some(loading) = loading
        && !loading
            .0
            .iter()
            .all(|h| asset_server.is_loaded_with_dependencies(h.id()))
    {
        return;
    }

    let now = Instant::now();
    let bench = &mut *bench;
    let timing = bench.frame > bench.warmup && bench.frame <= bench.warmup + bench.frames;

    if timing && let Some(last) = bench.last {
        bench.frame_ms.push((now - last).as_secs_f64() * 1000.0);
        for diagnostic in store.iter() {
            let path = diagnostic.path().as_str();
            if path.starts_with("render/")
                && let Some(value) = diagnostic.value()
            {
                bench
                    .diagnostics
                    .entry(path.to_string())
                    .or_default()
                    .push(value);
            }
        }
    }
    bench.last = Some(now);

    let end = bench.warmup + bench.frames;
    if bench.frame == end {
        commands
            .spawn(Screenshot::primary_window())
            .observe(save_to_disk(bench.screenshot.clone()));
    }
    // Leave a few frames for the screenshot to be read back and saved.
    if bench.frame == end + 5 {
        write_results(bench);
        exit.write(AppExit::Success);
    }
    bench.frame += 1;
}

fn median(values: &[f64]) -> f64 {
    let mut sorted = values.to_vec();
    sorted.sort_by(f64::total_cmp);
    sorted.get(sorted.len() / 2).copied().unwrap_or(f64::NAN)
}

fn write_results(bench: &Bench) {
    let mut diagnostics: Vec<_> = bench
        .diagnostics
        .iter()
        .map(|(path, values)| format!("    \"{path}\": {:.4}", median(values)))
        .collect();
    diagnostics.sort();

    let frames: Vec<_> = bench.frame_ms.iter().map(|ms| format!("{ms:.3}")).collect();
    let json = format!(
        "{{\n  \"scene\": \"{}\",\n  \"frame_ms_median\": {:.3},\n  \"frame_ms\": [{}],\n  \"diagnostics_median\": {{\n{}\n  }}\n}}\n",
        bench.name,
        median(&bench.frame_ms),
        frames.join(", "),
        diagnostics.join(",\n"),
    );
    std::fs::write(&bench.out, json).expect("couldn't write bench results");
    info!(
        "{}: median frame {:.2} ms",
        bench.name,
        median(&bench.frame_ms)
    );
}
