"""Round-trip test for the rename engine. Run: python test_engine.py"""

import hashlib
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import piexif
from PIL import Image

from engine.core import (Field, commit, default_pattern, find_manifests,
                         load_paths,
                         format_example, plan_renames, scan_folder, sort_photos,
                         suggest_groups, summarize_sources, undo,
                         validate_pattern)

SHOPS = [("Sunrise Kirana", 12), ("Metro Mart", 4), ("Gupta Stores", 4)]
# 12 photos: 4 + 4 + 4, with big gaps between shops


def make_jpeg(path: Path, when: datetime, with_exif: bool = True) -> None:
    img = Image.new("RGB", (64, 48), (when.minute * 4 % 255, 120, 200))
    if with_exif:
        exif = {"0th": {}, "Exif": {
            piexif.ExifIFD.DateTimeOriginal: when.strftime("%Y:%m:%d %H:%M:%S").encode()
        }, "GPS": {}, "1st": {}, "thumbnail": None}
        img.save(path, "jpeg", exif=piexif.dump(exif))
    else:
        img.save(path, "jpeg")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_folder(root: Path) -> None:
    base = datetime(2026, 9, 4, 9, 0, 0)
    n = 0
    for shop_index, (_, _) in enumerate(SHOPS):
        start = base + timedelta(hours=2 * shop_index)
        for i in range(4):
            n += 1
            make_jpeg(root / f"IMG_{1000 + n}.jpg", start + timedelta(minutes=3 * i))
    (root / "notes.txt").write_text("do not touch me\n")


def test_stripped_exif() -> None:
    """The realistic bad case: EXIF gone, every file downloaded in one go."""
    tmp = Path(tempfile.mkdtemp(prefix="renamer_stripped_"))
    try:
        # 12 photos, no EXIF, three camera-numbering runs, identical mtimes
        when = datetime(2026, 9, 4, 9, 0, 0)
        stamp = when.timestamp()
        for base in (1001, 1101, 1201):
            for i in range(4):
                f = tmp / f"IMG_{base + i}.jpg"
                make_jpeg(f, when, with_exif=False)
                os.utime(f, (stamp, stamp))

        photos = scan_folder(tmp)
        stats = summarize_sources(photos)
        assert stats.exif == 0 and stats.mtime == 12, stats
        assert not stats.timestamps_reliable, "should distrust identical mtimes"
        print(f"stripped EXIF: {stats.summary}")

        names = [p.name for p in photos]
        assert names == sorted(names), "should fall back to filename order"

        groups = suggest_groups(photos, 30)          # auto -> sequence
        assert [len(g) for g in groups] == [4, 4, 4], [len(g) for g in groups]
        print(f"grouping without timestamps: {[len(g) for g in groups]} (from filename numbering)")

        # time-based grouping would have collapsed to one block
        assert len(suggest_groups(photos, 30, mode="time")) == 1

        for label, idxs in zip(("Alpha", "Beta", "Gamma"), groups):
            for i in idxs:
                photos[i].group_label = label
        plans = plan_renames(photos, "Audit Q3", date_str="20260904")
        assert plans[0].new_name == "Audit_Q3_Alpha_20260904_001.jpg", plans[0].new_name
        result = commit(plans)
        assert result.renamed == 12
        restored = undo(result.manifest_path)
        assert len(restored.restored) == 12
        print("stripped-EXIF folder: renamed and undone cleanly")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_natural_order() -> None:
    """IMG_9 must not sort after IMG_10."""
    tmp = Path(tempfile.mkdtemp(prefix="renamer_order_"))
    try:
        when = datetime(2026, 9, 4, 9, 0, 0)
        for n in (2, 9, 10, 11):
            f = tmp / f"IMG_{n}.jpg"
            make_jpeg(f, when, with_exif=False)
            os.utime(f, (when.timestamp(), when.timestamp()))
        photos = scan_folder(tmp)
        assert [p.name for p in photos] == ["IMG_2.jpg", "IMG_9.jpg",
                                            "IMG_10.jpg", "IMG_11.jpg"], \
            [p.name for p in photos]
        print("natural order: IMG_2, IMG_9, IMG_10, IMG_11")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_custom_pattern() -> None:
    """She can rebuild the convention out of fields."""
    tmp = Path(tempfile.mkdtemp(prefix="renamer_pattern_"))
    try:
        build_folder(tmp)
        photos = scan_folder(tmp)
        for p in photos:
            p.group_label = "Sunrise Kirana"

        # Region_Shop_Date_Auditor_0001
        pattern = [Field("text", "West"), Field("shop"), Field("date", "2026-09-04"),
                   Field("text", "Priya"), Field("counter", "4")]
        validate_pattern(pattern)
        print("custom pattern example:", format_example(pattern))
        plans = plan_renames(photos, pattern=pattern)
        assert plans[0].new_name == "West_Sunrise_Kirana_20260904_Priya_0001.jpg", \
            plans[0].new_name
        assert plans[11].new_name.endswith("_0012.jpg"), plans[11].new_name
        assert len({p.new_name for p in plans}) == 12, "names must be unique"

        # shop-free pattern: no shop assignment required at all
        simple = [Field("text", "Audit"), Field("original"), Field("counter", "2")]
        for p in photos:
            p.group_label = ""
        plans2 = plan_renames(photos, pattern=simple)
        assert plans2[0].new_name == "Audit_IMG_1001_01.jpg", plans2[0].new_name
        print("shop-free pattern example:", plans2[0].new_name)

        # a pattern that cannot produce unique names is refused
        for bad, why in [([Field("text", "Audit"), Field("shop")], "no number"),
                         ([Field("text", "")], "empty text"),
                         ([Field("date", "4 Sept")], "bad date")]:
            try:
                validate_pattern(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"should have refused: {why}")
        print("bad patterns refused: no number, empty text, bad date")

        # round trip on the custom pattern
        for p in photos:
            p.group_label = "Sunrise Kirana"
        result = commit(plan_renames(photos, pattern=pattern))
        assert result.renamed == 12
        # a second pass now knows these came from us, whatever the pattern was
        again = scan_folder(tmp)
        for p in again:
            p.group_label = "Sunrise Kirana"
        assert all(p.already_renamed for p in plan_renames(again, pattern=pattern))
        print("already_renamed detected from the log, not the name shape")
        assert len(undo(result.manifest_path).restored) == 12
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_multi_folder_and_files() -> None:
    """Photos picked one by one, from more than one folder."""
    root = Path(tempfile.mkdtemp(prefix="renamer_multi_"))
    try:
        a, b = root / "shopA", root / "shopB"
        a.mkdir(); b.mkdir()
        when = datetime(2026, 9, 4, 9, 0, 0)
        for i in range(3):
            make_jpeg(a / f"IMG_{100 + i}.jpg", when + timedelta(minutes=i))
        for i in range(3):
            make_jpeg(b / f"IMG_{200 + i}.jpg", when + timedelta(hours=3, minutes=i))
        # a name that already exists in B, to prove collisions are per-folder
        make_jpeg(b / "Audit_Beta_20260904_001.jpg", when)

        # drop two loose files plus a whole folder
        photos = load_paths([a / "IMG_100.jpg", a / "IMG_101.jpg", b])
        assert len(photos) == 6, [p.name for p in photos]   # 2 loose + 4 in shopB
        assert len({p.path.parent for p in photos}) == 2
        print(f"load_paths: {len(photos)} photos from 2 folders "
              f"({[p.name for p in photos]})")

        # adding the same paths again must not duplicate
        photos = load_paths([a, b], existing=photos)
        assert len(photos) == 7, len(photos)
        print(f"re-adding both folders: {len(photos)} photos, no duplicates")

        # manual order is left exactly as arranged
        photos = [p for p in photos if p.name != "Audit_Beta_20260904_001.jpg"]
        photos.reverse()
        first = photos[0].name
        sort_photos(photos, "manual")
        assert photos[0].name == first, "manual sort must not reorder"
        print(f"manual order preserved (first = {first})")

        for p in photos:
            p.group_label = "Alpha" if p.path.parent == a else "Beta"
        plans = plan_renames(photos, pattern=[Field("text", "Audit"), Field("shop"),
                                              Field("date", "20260904"),
                                              Field("counter", "3")])
        # Beta_001 already exists in shopB and is NOT one of ours -> collision
        beta = [p for p in plans if "Beta" in p.new_name]
        assert any(p.collision for p in beta), "should flag the pre-existing name"
        print("per-folder collision detected in shopB only")

        # numbering follows list order, per folder+shop
        alpha = [p for p in plans if "Alpha" in p.new_name]
        assert [p.new_name[-7:] for p in alpha] == ["001.jpg", "002.jpg", "003.jpg"]

        # remove the clashing file, then commit across both folders
        (b / "Audit_Beta_20260904_001.jpg").unlink()
        plans = plan_renames(photos, pattern=[Field("text", "Audit"), Field("shop"),
                                              Field("date", "20260904"),
                                              Field("counter", "3")])
        result = commit(plans)
        assert len(result.manifest_paths) == 2, result.manifest_paths
        assert result.renamed == 6
        print(f"commit across 2 folders: {result.renamed} renamed, "
              f"{len(result.manifest_paths)} logs written")

        total = sum(len(undo(m).restored) for m in result.manifest_paths)
        assert total == 6
        print("undo across both folders: 6 restored")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="renamer_test_"))
    try:
        build_folder(tmp)
        before = {p.name: sha(p) for p in tmp.glob("*.jpg")}
        notes_before = (tmp / "notes.txt").read_text()

        photos = scan_folder(tmp)
        assert len(photos) == 12, f"expected 12 photos, got {len(photos)}"
        assert all(p.capture_source == "exif" for p in photos), "EXIF not read"
        print(f"scan_folder: {len(photos)} photos, all EXIF timestamps")

        groups = suggest_groups(photos, gap_minutes=30)
        assert len(groups) == 3, f"expected 3 groups, got {len(groups)}"
        assert [len(g) for g in groups] == [4, 4, 4]
        print(f"suggest_groups: {[len(g) for g in groups]}")

        for (shop, _), idxs in zip(SHOPS, groups):
            for i in idxs:
                photos[i].group_label = shop

        plans = plan_renames(photos, "Audit Q3", date_str="")
        assert not any(p.collision for p in plans), "unexpected collision"
        assert not any(p.already_renamed for p in plans)
        print("plan_renames sample:", plans[0].old_name, "->", plans[0].new_name)
        assert plans[0].new_name == "Audit_Q3_Sunrise_Kirana_20260904_001.jpg", plans[0].new_name

        result = commit(plans)
        print(f"commit: renamed {result.renamed}, log {result.manifest_path.name}")
        assert result.renamed == 12
        assert result.manifest_path.exists()
        for p in plans:
            assert (tmp / p.new_name).exists(), f"missing {p.new_name}"
            assert not p.photo.path.exists()

        # manifest is skipped by a re-scan, and renamed files are flagged
        rescanned = scan_folder(tmp)
        assert len(rescanned) == 12
        for p in rescanned:
            p.group_label = "X"
        replans = plan_renames(rescanned, "Audit Q3")
        assert all(p.already_renamed for p in replans), "already_renamed not detected"
        print("already_renamed: detected on all 12")

        manifests = find_manifests(tmp)
        assert len(manifests) == 1 and manifests[0].count == 12
        print(f"find_manifests: {manifests[0].path.name} ({manifests[0].count} rows)")

        undone = undo(manifests[0].path)
        assert len(undone.restored) == 12, undone
        assert not undone.missing and not undone.blocked
        after = {p.name: sha(p) for p in tmp.glob("*.jpg")}
        assert before == after, "round trip is NOT byte-identical"
        print("undo: 12 restored, all bytes identical")

        assert (tmp / "notes.txt").read_text() == notes_before
        assert manifests[0].path.exists(), "manifest should survive an undo"
        print("notes.txt untouched, manifest kept")

        # missing-file tolerance
        photos = scan_folder(tmp)
        for p in photos:
            p.group_label = "Solo"
        plans = plan_renames(photos, "Audit Q3")
        result = commit(plans)
        (tmp / plans[3].new_name).unlink()
        undone = undo(result.manifest_path)
        assert len(undone.restored) == 11 and len(undone.missing) == 1, undone
        print(f"undo with a deleted file: 11 restored, missing {undone.missing}")

        print()
        test_stripped_exif()
        test_natural_order()
        test_custom_pattern()
        test_multi_folder_and_files()
        print("\nALL TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
