"""Serialize a unified-planning ``Problem`` into the inputs an agent receives.

The goal is to hand the Claude agent the *same* information a TAMPEST solver
gets for one instance: the symbolic task model (types, objects, fluents,
initial state, goal, actions) plus the geometric data that the motion planner
consumes (SE2 configurations, robot/door footprints, motion models, and the
occupancy-grid map). The symbolic model is rendered as Markdown; the occupancy
map image and its YAML are copied into the sandbox so the agent can open them.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class MapExport:
    """A copied occupancy map and the metadata needed to read it."""

    yaml_name: str
    image_name: str
    resolution: float
    origin: tuple[float, float, float]
    width_px: int
    height_px: int
    width_m: float
    height_m: float


@dataclass
class SerializedProblem:
    """Everything written into the sandbox to describe one instance."""

    markdown: str
    maps: list[MapExport] = field(default_factory=list)


def _configuration_str(obj) -> str:
    """Render a configuration object's geometry (e.g. SE2 x/y/theta)."""
    cfg = getattr(obj, "configuration", None)
    if cfg is None:
        return "(no geometry)"
    x = getattr(cfg, "x", None)
    y = getattr(cfg, "y", None)
    theta = getattr(cfg, "theta", None)
    if x is not None and y is not None and theta is not None:
        return f"SE2(x={x:.3f}, y={y:.3f}, theta={theta:.4f} rad)"
    return str(cfg)


def _movable_str(obj) -> str:
    """Render a movable object's footprint and motion model."""
    footprint = getattr(obj, "footprint", None)
    motion_model = getattr(obj, "motion_model", None)
    params = getattr(obj, "motion_parameters", None)
    parts = []
    if motion_model is not None:
        parts.append(f"motion_model={motion_model}")
    if params:
        parts.append(f"motion_parameters={params}")
    if footprint is not None:
        parts.append(f"footprint={footprint}")
    return ", ".join(parts) if parts else "(no geometry)"


def _collect_occupancy_maps(problem) -> list:
    """Return the distinct OccupancyMap objects referenced by config types."""
    seen: dict[str, object] = {}
    for t in problem.user_types:
        if t.is_configuration_type():
            occ = getattr(t, "occupancy_map", None)
            if occ is not None and getattr(occ, "filename", None):
                seen.setdefault(occ.filename, occ)
    return list(seen.values())


def export_maps(problem, dest_dir: Path) -> list[MapExport]:
    """Copy every occupancy map (YAML + image) into ``dest_dir/maps``.

    Returns metadata describing each map, including pixel dimensions and the
    resolution/origin needed to convert between world and pixel coordinates.
    """
    maps_dir = dest_dir / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    exports: list[MapExport] = []

    for occ in _collect_occupancy_maps(problem):
        yaml_path = Path(occ.filename)
        with open(yaml_path) as f:
            meta = yaml.safe_load(f)
        image_rel = meta["image"]
        image_path = yaml_path.parent / image_rel

        shutil.copy2(yaml_path, maps_dir / yaml_path.name)
        shutil.copy2(image_path, maps_dir / Path(image_rel).name)

        resolution = float(meta.get("resolution", 1.0))
        raw_origin = [float(v) for v in meta.get("origin", [0.0, 0.0, 0.0])]
        origin = tuple((raw_origin + [0.0, 0.0, 0.0])[:3])

        width_px = height_px = 0
        try:
            from PIL import Image

            with Image.open(image_path) as im:
                width_px, height_px = im.size
        except Exception:  # noqa: BLE001 - image read is best-effort metadata
            pass

        exports.append(
            MapExport(
                yaml_name=f"maps/{yaml_path.name}",
                image_name=f"maps/{Path(image_rel).name}",
                resolution=resolution,
                origin=origin,  # type: ignore[arg-type]
                width_px=width_px,
                height_px=height_px,
                width_m=width_px * resolution,
                height_m=height_px * resolution,
            )
        )
    return exports


def _gather_configs(problem) -> list[tuple[str, float, float]]:
    """Return (name, x, y) for every configuration object with SE2 geometry."""
    out = []
    for t in problem.user_types:
        if not t.is_configuration_type():
            continue
        for o in problem.objects(t):
            cfg = getattr(o, "configuration", None)
            x = getattr(cfg, "x", None)
            y = getattr(cfg, "y", None)
            if x is not None and y is not None:
                out.append((o.name, float(x), float(y)))
    return out


def _render_ascii_map(
    image_path: Path,
    resolution: float,
    origin: tuple[float, float, float],
    configs: list[tuple[str, float, float]],
    target_cols: int = 48,
) -> str:
    """Render a downsampled occupancy grid plus a config-location table.

    The grid gives the agent exact obstacle geometry deterministically, without
    needing image tooling inside the sandbox. `#` is occupied (wall/closed
    door), `.` is free. A table lists each configuration's world coordinates
    and its (row, col) cell so the agent can locate it on the grid.
    """
    try:
        import numpy as np
        from PIL import Image

        with Image.open(image_path) as im:
            arr = np.asarray(im.convert("L"))
    except Exception:  # noqa: BLE001 - grid is a best-effort aid
        return ""

    height_px, width_px = arr.shape
    ox, oy = origin[0], origin[1]
    cell_px = max(1, round(width_px / target_cols))
    n_cols = (width_px + cell_px - 1) // cell_px
    n_rows = (height_px + cell_px - 1) // cell_px

    # Occupied if a dark pixel appears in the cell (occupied_thresh; negate=0).
    occupied = arr < 128
    rows = []
    for gr in range(n_rows):
        r0, r1 = gr * cell_px, min((gr + 1) * cell_px, height_px)
        line = []
        for gc in range(n_cols):
            c0, c1 = gc * cell_px, min((gc + 1) * cell_px, width_px)
            block = occupied[r0:r1, c0:c1]
            frac = block.mean() if block.size else 0.0
            line.append("#" if frac > 0.25 else ".")
        rows.append("".join(line))

    def world_to_cell(x: float, y: float) -> tuple[int, int]:
        px_col = (x - ox) / resolution
        px_row_from_top = height_px - (y - oy) / resolution
        return int(px_row_from_top // cell_px), int(px_col // cell_px)

    lines = [
        f"Occupancy grid (1 char = {cell_px} px = {cell_px * resolution:.1f} m). "
        "Row 0 is the TOP (largest y); column 0 is the LEFT (smallest x). "
        "`#`=occupied, `.`=free.",
        "```",
    ]
    lines.extend(rows)
    lines.append("```")
    lines.append("")
    lines.append("Configuration locations on this grid:")
    lines.append("")
    lines.append("| config | world (x, y) | grid (row, col) |")
    lines.append("|--------|--------------|-----------------|")
    for name, x, y in configs:
        gr, gc = world_to_cell(x, y)
        lines.append(f"| `{name}` | ({x:.1f}, {y:.1f}) | ({gr}, {gc}) |")
    return "\n".join(lines)


def _objects_section(problem) -> str:
    lines = ["## Objects (with geometry)", ""]
    for t in problem.user_types:
        objs = list(problem.objects(t))
        if not objs:
            continue
        kind = "movable" if t.is_movable_type() else (
            "configuration" if t.is_configuration_type() else "symbolic"
        )
        lines.append(f"### Type `{t.name}` ({kind})")
        for o in objs:
            if t.is_movable_type():
                lines.append(f"- `{o.name}`: {_movable_str(o)}")
            elif t.is_configuration_type():
                lines.append(f"- `{o.name}`: {_configuration_str(o)}")
            else:
                lines.append(f"- `{o.name}`")
        lines.append("")
    return "\n".join(lines)


def _fluents_section(problem) -> str:
    lines = ["## Fluents (state variables)", ""]
    for f in problem.fluents:
        lines.append(f"- `{f}`")
    lines.append("")
    return "\n".join(lines)


def _init_section(problem) -> str:
    lines = ["## Initial state", ""]
    for k, v in problem.explicit_initial_values.items():
        lines.append(f"- `{k} = {v}`")
    # Note default values for fluents that are not listed explicitly.
    defaults = getattr(problem, "fluents_defaults", {})
    if defaults:
        lines.append("")
        lines.append("Default initial values (apply to every unlisted instance):")
        for fl, val in defaults.items():
            lines.append(f"- `{fl}` defaults to `{val}`")
    lines.append("")
    return "\n".join(lines)


def _goal_section(problem) -> str:
    lines = ["## Goal", ""]
    for g in problem.goals:
        lines.append(f"- `{g}`")
    lines.append("")
    return "\n".join(lines)


def _actions_section(problem) -> str:
    lines = ["## Actions", ""]
    for a in problem.actions:
        params = ", ".join(f"{p.name}: {p.type}" for p in a.parameters)
        lines.append(f"### `{a.name}({params})`")
        pres = list(getattr(a, "preconditions", []))
        if pres:
            lines.append("Preconditions:")
            for c in pres:
                lines.append(f"- `{c}`")
        effs = list(getattr(a, "effects", []))
        if effs:
            lines.append("Effects:")
            for e in effs:
                lines.append(f"- `{e}`")
        mcs = list(getattr(a, "motion_constraints", []))
        if mcs:
            lines.append("Motion constraints (must be geometrically feasible):")
            for mc in mcs:
                movable = getattr(mc, "movable", "?")
                starting = getattr(mc, "starting", "?")
                waypoints = getattr(mc, "waypoints", "?")
                obstacles = getattr(mc, "static_obstacles", {})
                lines.append(
                    f"- `{type(mc).__name__}`: move `{movable}` from "
                    f"`{starting}` through `{waypoints}`, avoiding static "
                    f"obstacles `{obstacles}` (a collision-free path must exist "
                    f"for the chosen configurations)."
                )
        lines.append("")
    return "\n".join(lines)


def _maps_section(maps: list[MapExport], grids: list[str]) -> str:
    if not maps:
        return ""
    lines = ["## Occupancy map(s)", ""]
    for m, grid in zip(maps, grids):
        ox, oy, _ = m.origin
        lines.append(f"- Image `{m.image_name}` (YAML `{m.yaml_name}`)")
        lines.append(
            f"  - {m.width_px}x{m.height_px} px, resolution {m.resolution} m/px "
            f"=> world extent {m.width_m:.1f} m x {m.height_m:.1f} m"
        )
        lines.append(f"  - origin (world coords of pixel row=bottom, col=left): ({ox}, {oy})")
        lines.append("")
        if grid:
            lines.append(grid)
            lines.append("")
    lines.append(
        "The grid above gives the obstacle layout; the original image is also "
        "in `maps/` (open it with the Read tool for a higher-resolution view). "
        "A configuration is only usable if the footprint placed there does not "
        "overlap an obstacle, and a `move` is only feasible if a collision-free "
        "path connects the two configurations given current door positions."
    )
    lines.append("")
    return "\n".join(lines)


def serialize_problem(problem, dest_dir: Path) -> SerializedProblem:
    """Serialize ``problem`` to Markdown and export its maps into ``dest_dir``."""
    maps = export_maps(problem, dest_dir)
    configs = _gather_configs(problem)
    grids = [
        _render_ascii_map(dest_dir / m.image_name, m.resolution, m.origin, configs)
        for m in maps
    ]
    sections = [
        f"# TAMP problem: {problem.name}",
        "",
        "This is a single task-and-motion-planning instance. Produce a plan: a "
        "sequence of grounded actions that reaches the goal, where every action's "
        "preconditions hold in sequence and every motion constraint is "
        "geometrically feasible (collision-free).",
        "",
        _objects_section(problem),
        _fluents_section(problem),
        _init_section(problem),
        _goal_section(problem),
        _actions_section(problem),
        _maps_section(maps, grids),
    ]
    return SerializedProblem(markdown="\n".join(sections), maps=maps)
