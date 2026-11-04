//! A uniform grid over occluder bounds, for finding the occluders near a light.

use bevy::{platform::collections::HashMap, prelude::*, shape::Aabb2d};

/// Occluders that would span more cells than this go in a list that every query returns.
const MAX_CELLS_PER_OCCLUDER: i64 = 16;

pub(crate) struct OccluderGrid {
    cell_size: f32,
    cells: HashMap<IVec2, Vec<u32>>,
    large: Vec<u32>,
}

impl OccluderGrid {
    /// Builds a grid over `aabbs`. Queries return indices into this slice.
    pub fn new(aabbs: &[Aabb2d]) -> Self {
        // Cells about twice the average occluder size keep most occluders in one to four cells.
        let total: f32 = aabbs.iter().map(|a| (a.max - a.min).max_element()).sum();
        let cell_size = (2.0 * total / aabbs.len().max(1) as f32).max(1e-3);

        let mut grid = Self {
            cell_size,
            cells: default(),
            large: vec![],
        };
        for (i, aabb) in aabbs.iter().enumerate() {
            let (min, max) = grid.cell_range(aabb);
            if cell_count(min, max) > MAX_CELLS_PER_OCCLUDER {
                grid.large.push(i as u32);
                continue;
            }
            for y in min.y..=max.y {
                for x in min.x..=max.x {
                    grid.cells.entry(ivec2(x, y)).or_default().push(i as u32);
                }
            }
        }
        grid
    }

    fn cell_range(&self, aabb: &Aabb2d) -> (IVec2, IVec2) {
        (
            (aabb.min / self.cell_size).floor().as_ivec2(),
            (aabb.max / self.cell_size).floor().as_ivec2(),
        )
    }

    /// Writes to `out`, in ascending order, every occluder that shares a cell with `aabb`.
    /// This includes every occluder whose bounds intersect `aabb`.
    pub fn query(&self, aabb: &Aabb2d, out: &mut Vec<u32>) {
        out.clear();
        out.extend_from_slice(&self.large);

        let (min, max) = self.cell_range(aabb);
        if cell_count(min, max) > self.cells.len() as i64 {
            for (cell, occluders) in &self.cells {
                if cell.cmpge(min).all() && cell.cmple(max).all() {
                    out.extend_from_slice(occluders);
                }
            }
        } else {
            for y in min.y..=max.y {
                for x in min.x..=max.x {
                    if let Some(occluders) = self.cells.get(&ivec2(x, y)) {
                        out.extend_from_slice(occluders);
                    }
                }
            }
        }

        out.sort_unstable();
        out.dedup();
    }
}

fn cell_count(min: IVec2, max: IVec2) -> i64 {
    let size = |min: i32, max: i32| (max as i64 - min as i64 + 1).max(0);
    size(min.x, max.x).saturating_mul(size(min.y, max.y))
}
