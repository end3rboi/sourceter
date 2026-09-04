"""Photo batch renamer engine.

Pure-Python, no GUI imports. Everything here is testable from a terminal.

Public API:
    scan_folder(folder, sort='auto')        -> list[Photo]
    load_paths(paths, sort='auto')          -> list[Photo]   (files or folders)
    summarize_sources(photos)               -> SourceStats
    sort_photos(photos, mode='auto')        -> str
    suggest_groups(photos, gap_minutes=30, mode='auto') -> list[list[int]]
    plan_renames(photos, pattern=[Field(...)])  -> list[RenamePlan]
    format_example(pattern)                 -> str
    commit(plans, stamp_exif=False)         -> CommitResult
    find_manifests(folder)                  -> list[ManifestInfo]
    undo(manifest_path)                     -> UndoResult
"""

from __future__ import annotations

import csv
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PIL import Image

try:
    import piexif
except ImportError:  # stamping is optional
    piexif = None


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp", ".bmp"}

MANIFEST_PREFIX = "_rename_log_"
MANIFEST_GLOB = MANIFEST_PREFIX + "*.csv"

# Assignment_Shop_YYYYMMDD_001.ext
RENAMED_PATTERN = re.compile(r"^.+_.+_\d{8}_\d{3}$")

# EXIF tag ids for capture time, in priority order
_EXIF_DATE_TAGS = (36867, 36868, 306)  # DateTimeOriginal, DateTimeDigitized, DateTime


# --------------------------------------------------------------------------- #
# data types
# --------------------------------------------------------------------------- #

@dataclass
class Photo:
    path: Path
    name: str
    capture_time: datetime
    capture_source: str          # "exif" | "mtime"
    group_label: str = ""

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()


@dataclass
class SourceStats:
    total: int
    exif: int
    mtime: int
    spread_minutes: float
    numbered: int               # photos whose filename contains a number
    timestamps_reliable: bool

    @property
    def summary(self) -> str:
        if self.total == 0:
            return "No photos."
        if self.exif == self.total:
            return f"All {self.total} photos have camera timestamps."
        if self.exif == 0:
            return (f"None of the {self.total} photos have camera timestamps; "
                    f"all fall back to the file's modified date.")
        return (f"{self.exif} of {self.total} photos have camera timestamps; "
                f"the other {self.mtime} fall back to the file's modified date.")


@dataclass
class RenamePlan:
    photo: Photo
    new_name: str
    collision: bool = False
    already_renamed: bool = False

    @property
    def old_name(self) -> str:
        return self.photo.name

    @property
    def unchanged(self) -> bool:
        return self.new_name == self.photo.name


@dataclass
class CommitResult:
    manifest_paths: list[Path]
    renamed: int
    skipped: int = 0

    @property
    def manifest_path(self) -> Path:
        """The first log written — most runs only touch one folder."""
        return self.manifest_paths[0]


@dataclass
class ManifestInfo:
    path: Path
    run_time: datetime
    count: int


@dataclass
class UndoResult:
    restored: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# scanning
# --------------------------------------------------------------------------- #

def _parse_exif_datetime(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", "ignore")
    raw = str(raw).strip().rstrip("\x00")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def read_capture_time(path: Path) -> tuple[datetime, str]:
    """Return (capture_time, source) where source is 'exif' or 'mtime'."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if exif:
                # top-level IFD
                for tag in _EXIF_DATE_TAGS:
                    dt = _parse_exif_datetime(exif.get(tag))
                    if dt:
                        return dt, "exif"
                # Exif sub-IFD (0x8769) — where phones actually put it
                try:
                    sub = exif.get_ifd(0x8769)
                except Exception:
                    sub = {}
                for tag in _EXIF_DATE_TAGS:
                    dt = _parse_exif_datetime(sub.get(tag))
                    if dt:
                        return dt, "exif"
    except Exception:
        pass
    return datetime.fromtimestamp(path.stat().st_mtime), "mtime"


def is_manifest(path: Path) -> bool:
    return path.name.startswith(MANIFEST_PREFIX) and path.suffix.lower() == ".csv"


def make_photo(path: Path) -> Photo | None:
    """Build one Photo, or None if this file is not an image we handle."""
    path = Path(path)
    if not path.is_file() or is_manifest(path) or path.name.startswith("."):
        return None
    if path.suffix.lower() not in IMAGE_EXTS:
        return None
    when, source = read_capture_time(path)
    return Photo(path=path, name=path.name, capture_time=when, capture_source=source)


def load_paths(paths: Iterable, sort: str = "auto",
               existing: list[Photo] | None = None) -> list[Photo]:
    """Accept any mix of files and folders; folders are scanned one level.

    `existing` lets you add to a set already on screen without duplicating.
    """
    photos: list[Photo] = list(existing or [])
    seen = {p.path.resolve() for p in photos}
    for raw in paths:
        path = Path(raw)
        candidates = sorted(path.iterdir()) if path.is_dir() else [path]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            photo = make_photo(candidate)
            if photo:
                photos.append(photo)
                seen.add(resolved)
    sort_photos(photos, sort)
    return photos


def scan_folder(folder, sort: str = "auto") -> list[Photo]:
    """List image files in `folder`, ordered by `sort`:
    'auto' (capture time when the timestamps look trustworthy, else
    filename), 'capture', or 'name'."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f"Not a folder: {folder}")

    photos: list[Photo] = []
    for entry in sorted(folder.iterdir()):
        if not entry.is_file():
            continue
        if is_manifest(entry):
            continue
        if entry.name.startswith("."):
            continue
        if entry.suffix.lower() not in IMAGE_EXTS:
            continue
        when, source = read_capture_time(entry)
        photos.append(Photo(path=entry, name=entry.name,
                            capture_time=when, capture_source=source))

    sort_photos(photos, sort)
    return photos


# --------------------------------------------------------------------------- #
# ordering: timestamps are not always trustworthy
# --------------------------------------------------------------------------- #

_NUM_RE = re.compile(r"(\d+)")


def natural_key(name: str) -> tuple:
    """Sort key where IMG_9.jpg comes before IMG_10.jpg."""
    parts = _NUM_RE.split(Path(name).stem.lower())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def sequence_number(name: str) -> int | None:
    """The last run of digits in the stem, e.g. IMG_1042 -> 1042."""
    nums = _NUM_RE.findall(Path(name).stem)
    return int(nums[-1]) if nums else None


def summarize_sources(photos: Iterable[Photo]) -> SourceStats:
    """How trustworthy are these timestamps? Drives sorting and grouping."""
    photos = list(photos)
    total = len(photos)
    exif = sum(1 for p in photos if p.capture_source == "exif")
    if total < 2:
        spread = 0.0
    else:
        times = [p.capture_time for p in photos]
        spread = (max(times) - min(times)).total_seconds() / 60.0

    numbered = sum(1 for p in photos if sequence_number(p.name) is not None)

    # Timestamps are trusted when most came from EXIF and they actually spread
    # out. A folder downloaded in one go has a dozen identical mtimes: real
    # values, useless for ordering.
    reliable = total >= 2 and (exif / total) >= 0.6 and spread >= 2.0
    if total < 2:
        reliable = exif == total

    return SourceStats(total=total, exif=exif, mtime=total - exif,
                       spread_minutes=spread, numbered=numbered,
                       timestamps_reliable=reliable)


def sort_photos(photos: list[Photo], mode: str = "auto") -> str:
    """Sort in place. mode: 'auto' | 'capture' | 'name' | 'manual'.

    'manual' leaves the order exactly as given — the user arranged it."""
    if mode == "manual":
        return "manual"
    if mode == "auto":
        stats = summarize_sources(photos)
        mode = "capture" if stats.timestamps_reliable else "name"
    if mode == "capture":
        photos.sort(key=lambda p: (p.capture_time, natural_key(p.name)))
    elif mode == "name":
        photos.sort(key=lambda p: natural_key(p.name))
    else:
        raise ValueError(f"Unknown sort mode: {mode}")
    return mode


def suggest_groups(photos: Iterable[Photo], gap_minutes: int = 30,
                   mode: str = "auto", seq_gap: int = 5) -> list[list[int]]:
    """Split the photo list into runs.

    mode 'time'     — split on a capture-time gap larger than gap_minutes.
    mode 'sequence' — split where the camera's own numbering jumps by more
                      than seq_gap (IMG_1004 -> IMG_1099), which survives
                      EXIF stripping as long as filenames survive.
    mode 'auto'     — 'time' when the timestamps look trustworthy, else
                      'sequence', else one group.
    """
    photos = list(photos)
    if not photos:
        return []

    stats = summarize_sources(photos)
    if mode == "auto":
        if stats.timestamps_reliable:
            mode = "time"
        elif stats.numbered == stats.total:
            mode = "sequence"
        else:
            mode = "none"

    if mode == "none":
        return [list(range(len(photos)))]

    groups: list[list[int]] = [[0]]
    for i in range(1, len(photos)):
        if mode == "time":
            gap = (photos[i].capture_time
                   - photos[i - 1].capture_time).total_seconds() / 60.0
            split = gap > gap_minutes
        elif mode == "sequence":
            a = sequence_number(photos[i - 1].name)
            b = sequence_number(photos[i].name)
            split = a is not None and b is not None and abs(b - a) > seq_gap
        else:
            raise ValueError(f"Unknown grouping mode: {mode}")
        (groups.append([i]) if split else groups[-1].append(i))
    return groups


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #

def sanitize(text: str) -> str:
    """Make a filename-safe token: no spaces, no separators, no accents."""
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_-")
    return text


# --- the filename pattern ---------------------------------------------------- #

# kind -> (label shown in the UI, does it take a typed value?)
FIELD_KINDS: dict[str, tuple[str, bool]] = {
    "text":     ("Text", True),
    "shop":     ("Shop name", False),
    "date":     ("Date", True),
    "counter":  ("Number", True),
    "original": ("Original filename", False),
}


@dataclass
class Field:
    """One underscore-separated part of the filename."""
    kind: str
    value: str = ""

    def __post_init__(self):
        if self.kind not in FIELD_KINDS:
            raise ValueError(f"Unknown field: {self.kind}")

    @property
    def label(self) -> str:
        return FIELD_KINDS[self.kind][0]

    @property
    def takes_value(self) -> bool:
        return FIELD_KINDS[self.kind][1]


def default_pattern(assignment: str = "Assignment", date_str: str = "") -> list[Field]:
    """Assignment_Shop_YYYYMMDD_001 — the convention we started from."""
    return [Field("text", assignment), Field("shop"),
            Field("date", date_str), Field("counter", "")]


def normalize_date(raw: str) -> str:
    """Accept 20260904, 2026-09-04, 04/09/2026 -> 8 digits. '' means per-photo."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 8:
        raise ValueError("Date must have 8 digits, e.g. 20260904 or 2026-09-04.")
    return digits


def validate_pattern(fields: list[Field]) -> None:
    """Raise ValueError if this pattern cannot produce unique names."""
    if not fields:
        raise ValueError("The filename pattern is empty — add at least one field.")
    for f in fields:
        if f.kind == "text" and not sanitize(f.value):
            raise ValueError("One of the Text fields is empty. Fill it in or remove it.")
        if f.kind == "date":
            normalize_date(f.value)
        if f.kind == "counter" and f.value and not f.value.strip().isdigit():
            raise ValueError("Number width must be a digit, e.g. 3 for 001.")
    kinds = {f.kind for f in fields}
    if "counter" not in kinds and "original" not in kinds:
        raise ValueError(
            "Add a Number field (or Original filename), otherwise every photo "
            "in a shop would get exactly the same name.")


def _render_field(field: Field, photo: "Photo | None", seq: int,
                  sample: bool = False) -> str:
    if field.kind == "text":
        return sanitize(field.value)
    if field.kind == "shop":
        if sample:
            return sanitize(field.value or "Sunflower furniture shop")
        return sanitize(photo.group_label)
    if field.kind == "date":
        fixed = normalize_date(field.value)
        if fixed:
            return fixed
        if sample or photo is None:
            return datetime.now().strftime("%Y%m%d")
        return photo.capture_time.strftime("%Y%m%d")
    if field.kind == "counter":
        width = int(field.value) if str(field.value).strip().isdigit() else 3
        width = max(1, min(width, 9))
        return f"{seq:0{width}d}"
    if field.kind == "original":
        return sanitize(Path(photo.name).stem) if photo else "IMG_1042"
    return ""


def render_name(fields: list[Field], photo: "Photo", seq: int) -> str:
    parts = [_render_field(f, photo, seq) for f in fields]
    return "_".join(p for p in parts if p) + photo.suffix


def format_example(fields: list[Field]) -> str:
    """A live sample for the UI. Never touches disk."""
    try:
        parts = [_render_field(f, None, 1, sample=True) for f in fields]
    except ValueError as exc:
        return str(exc)
    joined = "_".join(p for p in parts if p)
    return (joined + ".jpg") if joined else "(empty)"


def previous_new_names(folder: Path) -> set[str]:
    """Every name this tool has produced in this folder before, from the logs."""
    names: set[str] = set()
    for info in find_manifests(folder):
        for row in _read_manifest(info.path):
            names.add(row.get("new_name", "").lower())
    return names


def looks_renamed(name: str) -> bool:
    """Fallback shape check for the default convention, used when no log exists."""
    return bool(RENAMED_PATTERN.match(Path(name).stem))


def plan_renames(photos: Iterable[Photo], assignment: str | None = None,
                 date_str: str = "",
                 pattern: list[Field] | None = None) -> list[RenamePlan]:
    """Pure: build the new names. Touches nothing on disk but existence checks.

    Either pass a `pattern` (list of Field), or an `assignment` string to use
    the default Assignment_Shop_Date_Number convention.
    """
    photos = list(photos)
    if not photos:
        return []

    if pattern is None:
        if not sanitize(assignment or ""):
            raise ValueError("Assignment name is empty.")
        pattern = default_pattern(assignment, date_str)
    validate_pattern(pattern)

    needs_shop = any(f.kind == "shop" for f in pattern)
    if needs_shop:
        unassigned = [p.name for p in photos if not sanitize(p.group_label)]
        if unassigned:
            raise ValueError(
                f"{len(unassigned)} photo(s) have no shop name yet, "
                f"starting with {unassigned[0]}.")

    # Photos can come from several folders at once, so every disk check is
    # scoped to the folder that photo actually lives in.
    folders = {p.path.parent for p in photos}
    existing = {f: {e.name.lower() for e in f.iterdir() if e.is_file()}
                for f in folders}
    originals = {f: {p.name.lower() for p in photos if p.path.parent == f}
                 for f in folders}
    seen_before = {f: previous_new_names(f) for f in folders}

    counters: dict[tuple, int] = {}
    plans: list[RenamePlan] = []
    taken: set[tuple[Path, str]] = set()

    for photo in photos:
        folder = photo.path.parent
        # The number restarts whenever anything else in the name changes.
        key = tuple(_render_field(f, photo, 0) for f in pattern
                    if f.kind != "counter")
        counters[key] = counters.get(key, 0) + 1
        new_name = render_name(pattern, photo, counters[key])

        collision = (folder, new_name.lower()) in taken
        if not collision and new_name.lower() != photo.name.lower():
            if (new_name.lower() in existing[folder]
                    and new_name.lower() not in originals[folder]):
                collision = True

        taken.add((folder, new_name.lower()))
        plans.append(RenamePlan(
            photo=photo, new_name=new_name, collision=collision,
            already_renamed=(photo.name.lower() in seen_before[folder]
                             or looks_renamed(photo.name))))
    return plans


# --------------------------------------------------------------------------- #
# commit
# --------------------------------------------------------------------------- #

MANIFEST_FIELDS = ["original_name", "new_name", "group_label",
                   "capture_time", "capture_source", "run_timestamp"]


def _stamp_exif(path: Path, original_name: str) -> None:
    if piexif is None or path.suffix.lower() not in {".jpg", ".jpeg"}:
        return
    try:
        exif_dict = piexif.load(str(path))
        exif_dict["0th"][piexif.ImageIFD.ImageDescription] = original_name.encode("utf-8")
        piexif.insert(piexif.dump(exif_dict), str(path))
    except Exception:
        pass


def commit(plans: list[RenamePlan], stamp_exif: bool = False) -> CommitResult:
    """Write the manifest, then rename in two phases. Refuses to run on collisions."""
    plans = [p for p in plans if not p.unchanged]
    if not plans:
        raise ValueError("Nothing to rename.")
    if any(p.collision for p in plans):
        raise ValueError("Refusing to run: some target names already exist.")

    run = datetime.now()
    stamp = run.strftime("%Y-%m-%d_%H%M%S")
    by_folder: dict[Path, list[RenamePlan]] = {}
    for p in plans:
        by_folder.setdefault(p.photo.path.parent, []).append(p)

    manifests: list[Path] = []
    for folder, folder_plans in by_folder.items():
        manifest_path = folder / f"{MANIFEST_PREFIX}{stamp}.csv"

        # 1. manifest first, so a crash mid-run still leaves a complete record
        with manifest_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
            writer.writeheader()
            for p in folder_plans:
                writer.writerow({
                    "original_name": p.photo.name,
                    "new_name": p.new_name,
                    "group_label": p.photo.group_label,
                    "capture_time": p.photo.capture_time.isoformat(timespec="seconds"),
                    "capture_source": p.photo.capture_source,
                    "run_timestamp": run.isoformat(timespec="seconds"),
                })
        manifests.append(manifest_path)

        # 2. everything to a temp name
        temps: list[tuple[Path, str]] = []
        for i, p in enumerate(folder_plans):
            temp = folder / f".__rename_tmp_{stamp}_{i:04d}{p.photo.suffix}"
            os.replace(p.photo.path, temp)
            temps.append((temp, p.new_name))

        # 3. temp -> final
        for temp, final in temps:
            os.replace(temp, folder / final)

        if stamp_exif:
            for p in folder_plans:
                _stamp_exif(folder / p.new_name, p.photo.name)

    return CommitResult(manifest_paths=manifests, renamed=len(plans))


# --------------------------------------------------------------------------- #
# undo
# --------------------------------------------------------------------------- #

def _read_manifest(manifest_path: Path) -> list[dict]:
    with Path(manifest_path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def find_manifests(folder) -> list[ManifestInfo]:
    """Most recent first."""
    folder = Path(folder)
    out: list[ManifestInfo] = []
    for path in folder.glob(MANIFEST_GLOB):
        rows = _read_manifest(path)
        try:
            run_time = datetime.fromisoformat(rows[0]["run_timestamp"])
        except (IndexError, KeyError, ValueError):
            run_time = datetime.fromtimestamp(path.stat().st_mtime)
        out.append(ManifestInfo(path=path, run_time=run_time, count=len(rows)))
    out.sort(key=lambda m: m.run_time, reverse=True)
    return out


def undo(manifest_path) -> UndoResult:
    """Reverse one run. Missing files are reported, not fatal."""
    manifest_path = Path(manifest_path)
    folder = manifest_path.parent
    rows = _read_manifest(manifest_path)
    result = UndoResult()

    stamp = datetime.now().strftime("%H%M%S")
    temps: list[tuple[Path, str]] = []

    for i, row in enumerate(rows):
        current = folder / row["new_name"]
        original = folder / row["original_name"]
        if not current.exists():
            result.missing.append(row["new_name"])
            continue
        if original.exists() and original.resolve() != current.resolve():
            result.blocked.append(row["original_name"])
            continue
        temp = folder / f".__undo_tmp_{stamp}_{i:04d}{current.suffix}"
        os.replace(current, temp)
        temps.append((temp, row["original_name"]))

    for temp, original_name in temps:
        os.replace(temp, folder / original_name)
        result.restored.append(original_name)

    return result
