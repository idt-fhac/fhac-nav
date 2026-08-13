"""
c3nav Exchange Format — Manifest Schema

The manifest.json is the root descriptor for a c3nav data export bundle.
It captures all instance-level configuration needed to correctly interpret
and re-import the accompanying per-model JSON files.

Design principles:
  - Projection and coordinate system metadata is mandatory — coordinates
    in the geometry files are meaningless without it.
  - Bounds are derived from the Source model's max_bounds() at export time.
  - The file listing declares which model files are present, allowing
    partial exports (e.g. geometry-only, graph-only).
  - Grid configuration is optional since not all instances use it.
  - The format_version follows semver for forward/backward compat signaling.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Sequence

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

#: Bump MAJOR when the schema changes in a backward-incompatible way,
#: MINOR for additive changes, PATCH for documentation/metadata tweaks.
FORMAT_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

class ProjectionInfo(BaseModel):
    """
    Describes how to convert between WGS84 and the c3nav-internal
    2-D Cartesian coordinate system used in all geometry files.

    At minimum, ``pipeline`` must be set.  The additional ``proj4``,
    ``zero_point``, ``rotation``, and ``rotation_matrix`` fields mirror
    the values from the ``/api/v2/map/projection/`` endpoint and the
    ``[projection]`` section of the instance's ``c3nav.cfg``.
    """
    pipeline: Optional[str] = Field(
        None,
        description=(
            "Full PROJ pipeline string (as returned by the projection API). "
            "This is the authoritative, self-contained transformation string."
        ),
        examples=[
            "+proj=pipeline +step +proj=utm +zone=32 +datum=WGS84 +units=m "
            "+step +proj=affine +xoff=-565400 +yoff=-5932700 +no_defs"
        ],
    )
    proj4: Optional[str] = Field(
        None,
        description=(
            "Original proj4 string from the instance configuration, "
            "before zero_point/rotation transforms are applied."
        ),
        examples=["+proj=utm +zone=32 +datum=WGS84 +units=m"],
    )
    zero_point: Optional[tuple[float, float]] = Field(
        None,
        description=(
            "The (x, y) offset subtracted from projected coordinates to "
            "move the map origin near (0, 0).  In projected CRS units (meters)."
        ),
        examples=[(565400.0, 5932700.0)],
    )
    rotation: Optional[float] = Field(
        None,
        description=(
            "Counter-clockwise rotation in degrees applied after projection "
            "and zero-point offset."
        ),
        examples=[0.0],
    )
    rotation_matrix: Optional[tuple[
        float, float, float, float,
        float, float, float, float,
        float, float, float, float,
        float, float, float, float,
    ]] = Field(
        None,
        description=(
            "4×4 affine transformation matrix (row-major, 16 floats) applied "
            "after projection.  If ``rotation`` was set, this is derived from it."
        ),
    )


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

class GridInfo(BaseModel):
    """
    Optional grid overlay used for the venue coordinate label system
    (e.g. "A1", "B3").
    """
    rows: Sequence[float] = Field(
        description="Y-axis boundary coordinates defining grid rows, in ascending order.",
    )
    cols: Sequence[float] = Field(
        description="X-axis boundary coordinates defining grid columns, in ascending order.",
    )
    invert_x: bool = Field(
        False,
        description="Whether the column labels run right-to-left.",
    )
    invert_y: bool = Field(
        False,
        description="Whether the row labels run top-to-bottom.",
    )


# ---------------------------------------------------------------------------
# File listing
# ---------------------------------------------------------------------------

class ExportSection(str, Enum):
    """
    Identifies which logical section a data file belongs to.
    Used for selective import (e.g. import only geometry, skip graph).
    """
    GEOMETRY = "geometry"
    GRAPH = "graph"
    LOCATIONS = "locations"
    ACCESS = "access"
    OVERLAYS = "overlays"
    THEMES = "themes"
    SOURCES = "sources"


class ExportFileEntry(BaseModel):
    """
    Describes one per-model JSON file included in the export bundle.
    """
    filename: str = Field(
        description="Relative path within the export bundle (e.g. 'spaces.json').",
        examples=["spaces.json"],
    )
    model: str = Field(
        description=(
            "Django model label in 'app_label.ModelName' format. "
            "Used by the importer to resolve the target model."
        ),
        examples=["mapdata.Space"],
    )
    section: ExportSection = Field(
        description="Logical section this file belongs to.",
        examples=[ExportSection.GEOMETRY],
    )
    record_count: int = Field(
        description="Number of records in the file at export time.",
        examples=[42],
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description=(
            "List of model labels that must be imported before this file. "
            "Defines the import ordering DAG."
        ),
        examples=[["mapdata.Level"]],
    )


# ---------------------------------------------------------------------------
# Manifest (root)
# ---------------------------------------------------------------------------

class ExportManifest(BaseModel):
    """
    Root schema for ``manifest.json`` in a c3nav export bundle.

    This file is always the first thing an importer reads.  It provides
    enough context to validate compatibility, resolve the coordinate system,
    and determine the import order for the accompanying data files.
    """

    # -- Format metadata ---------------------------------------------------
    format_version: str = Field(
        FORMAT_VERSION,
        description=(
            "Semantic version of the c3nav exchange format. "
            "Importers should refuse bundles with an incompatible MAJOR version."
        ),
        examples=["1.0.0"],
    )

    # -- Instance metadata -------------------------------------------------
    c3nav_version: Optional[str] = Field(
        None,
        description="c3nav software version (git hash or release tag) that produced this export.",
    )
    instance_title: Optional[str] = Field(
        None,
        description="Human-readable name of the exported instance (e.g. '37C3', 'CCH').",
    )
    exported_at: datetime = Field(
        description="UTC timestamp of when this export was created.",
    )

    # -- Coordinate system -------------------------------------------------
    projection: ProjectionInfo = Field(
        description=(
            "Coordinate reference system configuration. "
            "All geometry coordinates in the bundle are expressed in the "
            "c3nav-internal 2-D Cartesian system described by this projection."
        ),
    )
    bounds: tuple[
        tuple[float, float],
        tuple[float, float],
    ] = Field(
        description=(
            "Bounding box of the entire map as ((min_x, min_y), (max_x, max_y)), "
            "derived from Source.max_bounds() at export time."
        ),
        examples=[((0.0, 0.0), (300.0, 200.0))],
    )

    # -- Optional instance config ------------------------------------------
    grid: Optional[GridInfo] = Field(
        None,
        description="Grid overlay configuration, if the instance uses one.",
    )
    initial_level: Optional[str] = Field(
        None,
        description="Level index to show by default when the map loads.",
    )
    initial_bounds: Optional[tuple[
        tuple[float, float],
        tuple[float, float],
    ]] = Field(
        None,
        description=(
            "Initial viewport bounds as ((min_x, min_y), (max_x, max_y)). "
            "If not set, the importer should use the full 'bounds'."
        ),
    )
    wifi_ssids: list[str] = Field(
        default_factory=list,
        description="WiFi SSIDs used for indoor positioning at this venue.",
    )

    # -- File listing ------------------------------------------------------
    files: list[ExportFileEntry] = Field(
        description=(
            "Ordered list of data files in the bundle. "
            "The order respects the dependency DAG: each file's "
            "depends_on references appear earlier in the list."
        ),
    )


# ---------------------------------------------------------------------------
# Convenience: default file listing for a full export
# ---------------------------------------------------------------------------

#: Canonical ordering of all exportable models.
#: Each tuple is (filename, model_label, section, depends_on).
DEFAULT_EXPORT_FILES: list[tuple[str, str, ExportSection, list[str]]] = [
    # --- Dependency-free ---
    ("waytypes.json",                "mapdata.WayType",                 ExportSection.GRAPH,     []),
    ("labelsettings.json",           "mapdata.LabelSettings",           ExportSection.LOCATIONS, []),
    ("locationgroupcategories.json", "mapdata.LocationGroupCategory",   ExportSection.LOCATIONS, []),
    ("accessrestrictions.json",      "mapdata.AccessRestriction",       ExportSection.ACCESS,    []),

    # --- Top-level containers ---
    ("levels.json",              "mapdata.Level",                   ExportSection.GEOMETRY,  []),
    ("sources.json",             "mapdata.Source",                  ExportSection.SOURCES,   []),

    # --- Depend on categories / restrictions ---
    ("accessrestrictiongroups.json", "mapdata.AccessRestrictionGroup", ExportSection.ACCESS,
     ["mapdata.AccessRestriction"]),
    ("locationgroups.json",      "mapdata.LocationGroup",           ExportSection.LOCATIONS,
     ["mapdata.LocationGroupCategory"]),
    ("obstaclegroups.json",      "mapdata.ObstacleGroup",           ExportSection.GEOMETRY,  []),

    # --- Level children ---
    ("buildings.json",           "mapdata.Building",                ExportSection.GEOMETRY,  ["mapdata.Level"]),
    ("spaces.json",              "mapdata.Space",                   ExportSection.GEOMETRY,  ["mapdata.Level"]),
    ("doors.json",               "mapdata.Door",                    ExportSection.GEOMETRY,  ["mapdata.Level"]),

    # --- Space children (geometry) ---
    ("holes.json",               "mapdata.Hole",                    ExportSection.GEOMETRY,  ["mapdata.Space"]),
    ("areas.json",               "mapdata.Area",                    ExportSection.GEOMETRY,  ["mapdata.Space"]),
    ("stairs.json",              "mapdata.Stair",                   ExportSection.GEOMETRY,  ["mapdata.Space"]),
    ("ramps.json",               "mapdata.Ramp",                    ExportSection.GEOMETRY,  ["mapdata.Space"]),
    ("obstacles.json",           "mapdata.Obstacle",                ExportSection.GEOMETRY,  ["mapdata.Space"]),
    ("lineobstacles.json",       "mapdata.LineObstacle",            ExportSection.GEOMETRY,  ["mapdata.Space"]),
    ("columns.json",             "mapdata.Column",                  ExportSection.GEOMETRY,  ["mapdata.Space"]),
    ("pois.json",                "mapdata.POI",                     ExportSection.GEOMETRY,  ["mapdata.Space"]),
    ("altitudemarkers.json",     "mapdata.AltitudeMarker",          ExportSection.GEOMETRY,  ["mapdata.Space"]),

    # --- Graph ---
    ("graphnodes.json",          "mapdata.GraphNode",               ExportSection.GRAPH,     ["mapdata.Space"]),
    ("graphedges.json",          "mapdata.GraphEdge",               ExportSection.GRAPH,
     ["mapdata.GraphNode", "mapdata.WayType"]),

    # --- Locations (depend on groups) ---
    ("locationredirects.json",   "mapdata.LocationRedirect",        ExportSection.LOCATIONS, ["mapdata.LocationGroup"]),

    # --- Overlays ---
    ("dataoverlays.json",        "mapdata.DataOverlay",             ExportSection.OVERLAYS,  []),
    ("dataoverlayfeatures.json", "mapdata.DataOverlayFeature",      ExportSection.OVERLAYS,
     ["mapdata.DataOverlay", "mapdata.Level"]),

    # --- Themes ---
    ("themes.json",              "mapdata.Theme",                   ExportSection.THEMES,    []),

    # --- Descriptions ---
    ("leavedescriptions.json",   "mapdata.LeaveDescription",        ExportSection.GEOMETRY,  ["mapdata.Space"]),
    ("crossdescriptions.json",   "mapdata.CrossDescription",        ExportSection.GEOMETRY,  ["mapdata.Space"]),
]


def build_default_file_entries() -> list[ExportFileEntry]:
    """Build the default files list with record_count=0 (to be filled at export time)."""
    return [
        ExportFileEntry(
            filename=filename,
            model=model,
            section=section,
            record_count=0,
            depends_on=depends_on,
        )
        for filename, model, section, depends_on in DEFAULT_EXPORT_FILES
    ]
