import zipfile
from pathlib import Path

from comicmeta._commands.organize import _canonical_file_name, _file_number


def make_cbz(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.jpg", b"page")


def test_canonical_file_name_padding():
    assert _canonical_file_name("Hawkeye (1994) #7", ".cbz", "Hawkeye", "1994") == "Hawkeye (1994) #007.cbz"
    assert _canonical_file_name("Hawkeye (1994) #007", ".cbz", "Hawkeye", "1994") == "Hawkeye (1994) #007.cbz"
    # keep non-integer numbers as-is
    assert _canonical_file_name("Hawkeye (1994) #1.5", ".cbz", "Hawkeye", "1994") == "Hawkeye (1994) #1.5.cbz"
    assert _file_number("Batman.cbr") is None


def test_canonical_file_name_keeps_suffix():
    assert _canonical_file_name("Hawkeye (1983) #2", ".cbr", "Hawkeye", "1983") == "Hawkeye (1983) #002.cbr"


def test_split_folder():
    from comicmeta._commands.organize import _split_folder
    assert _split_folder("Aquaman Vol. 5 (1994)") == ("Aquaman Vol. 5", "1994")
    assert _split_folder("Hawkeye (1983)") == ("Hawkeye", "1983")
    assert _split_folder("No Year Here") == (None, None)


def test_clean_series_strips_volume_tags():
    from comicmeta._commands.organize import _clean_series
    assert _clean_series("Aquaman Vol. 5") == "Aquaman"
    assert _clean_series("Aquaman Vol. 5 Annual") == "Aquaman Annual"
    assert _clean_series("Aquaman v5") == "Aquaman"
    assert _clean_series("Hawkeye") == "Hawkeye"
    assert _clean_series("Batman - Year One - The Deluxe Edition") == "Batman - Year One - The Deluxe Edition"


def test_canonical_folder_name():
    from comicmeta._commands.organize import _canonical_folder_name
    assert _canonical_folder_name("Aquaman Vol. 5 (1994)") == "Aquaman (1994)"
    assert _canonical_folder_name("Aquaman Vol. 5 Annual (1995)") == "Aquaman Annual (1995)"
    assert _canonical_folder_name("Hawkeye (1983)") is None  # already standard


def test_file_number_and_canonical_name():
    from comicmeta._commands.organize import _file_number, _canonical_file_name
    assert _file_number("Aquaman v5 000 (1994)") == "000"
    assert _file_number("Aquaman 057 (1999)") == "057"
    assert _file_number("Hawkeye (1983) #001") == "001"
    assert _file_number("Batman - Year One - The Deluxe Edition (2017) HC") is None
    assert _file_number("Daredevil 01 (of 5) (1993)") == "01"
    assert _file_number("Aquaman (1998-11) 1000000 (digital) (Release)") == "1000000"
    assert _file_number("Aquaman 1000000 (1998-11) (digital) (Release)") == "1000000"
    assert _canonical_file_name("Aquaman v5 000 (1994)", ".cbz", "Aquaman", "1994") == "Aquaman (1994) #000.cbz"
    assert _canonical_file_name("Aquaman Annual 001 (1995)", ".cbz", "Aquaman Annual", "1995") == "Aquaman Annual (1995) #001.cbz"
    assert _canonical_file_name("Hawkeye (1983) #001", ".cbz", "Hawkeye", "1983") == "Hawkeye (1983) #001.cbz"
    assert _canonical_file_name("Batman HC", ".cbz", "Batman", "2017") is None


def test_canonical_collection_name():
    assert _canonical_file_name(
        "Daredevil Omnibus v01 (2017) (Digital-Empire)", ".cbz", "Daredevil Omnibus", "2017"
    ) == "Daredevil Omnibus (2017) Vol. 01.cbz"
    assert _canonical_file_name(
        "Batman Deluxe Edition", ".cbz", "Batman Deluxe Edition", "2017"
    ) is None


def test_run_proposes_folder_and_file_renames(tmp_path, monkeypatch):
    import io, contextlib
    from argparse import Namespace
    from comicmeta._commands.organize import run
    # Aquaman structure: folder with Vol. 5 + mixed filenames
    make_cbz(tmp_path / "DC/Aquaman Vol. 5 (1994)/Aquaman v5 000 (1994).cbz")
    make_cbz(tmp_path / "DC/Aquaman Vol. 5 (1994)/Aquaman 057 (1999).cbz")
    # Already-standard folder untouched
    make_cbz(tmp_path / "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz")
    args = Namespace(source=tmp_path, dry_run=True, execute=False, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)
    out = buf.getvalue()
    assert "Aquaman Vol. 5 (1994)/ → Aquaman (1994)/" in out
    assert "Aquaman v5 000 (1994).cbz → Aquaman (1994) #000.cbz" in out
    assert "Aquaman 057 (1999).cbz → Aquaman (1994) #057.cbz" in out
    assert "Hawkeye (1983) #001.cbz →" not in out  # unchanged


def test_run_execute_renames(tmp_path):
    import io, contextlib
    from argparse import Namespace
    from comicmeta._commands.organize import run
    make_cbz(tmp_path / "DC/Aquaman Vol. 5 (1994)/Aquaman v5 000 (1994).cbz")
    make_cbz(tmp_path / "DC/Aquaman Vol. 5 (1994)/Aquaman 057 (1999).cbz")
    args = Namespace(source=tmp_path, dry_run=False, execute=True, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)
    assert (tmp_path / "DC/Aquaman (1994)/Aquaman (1994) #000.cbz").is_file()
    assert (tmp_path / "DC/Aquaman (1994)/Aquaman (1994) #057.cbz").is_file()
    assert not (tmp_path / "DC/Aquaman Vol. 5 (1994)").exists()


def test_run_execute_skips_duplicate_normalized_destinations(tmp_path):
    import io, contextlib
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "DC/Batman Vol. 1 (2016)/Batman 1 (2016).cbz")
    make_cbz(tmp_path / "DC/Batman Vol. 1 (2016)/Batman #001.cbz")
    args = Namespace(source=tmp_path, dry_run=False, execute=True, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)

    assert "skipped=1" in buf.getvalue()
    assert (tmp_path / "DC/Batman (2016)/Batman (2016) #001.cbz").is_file()


def test_run_infers_noisy_folder_and_collected_issue_names(tmp_path):
    from argparse import Namespace
    from comicmeta._commands.organize import run
    import contextlib
    import io

    folder = "Daredevil - The Man Without Fear 01-05 (1993-1994) GetComics.INFO"
    make_cbz(tmp_path / f"Marvel/{folder}/Daredevil- The Man Without Fear 01 (of 5) (1993) (Digital).cbz")
    make_cbz(tmp_path / f"Marvel/{folder}/Daredevil- The Man Without Fear 02 (of 5) (1993) (Digital).cbz")
    args = Namespace(source=tmp_path, dry_run=False, execute=True, log=None, no_color=True)
    with contextlib.redirect_stdout(io.StringIO()):
        run(args)

    target = tmp_path / "Marvel/Daredevil - The Man Without Fear (1993)"
    assert (target / "Daredevil - The Man Without Fear (1993) #001.cbz").is_file()
    assert (target / "Daredevil - The Man Without Fear (1993) #002.cbz").is_file()


def test_loose_file_in_container_gets_new_series_folder(tmp_path):
    """A comic loose in a publisher root gets a series folder INSIDE it."""
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "Marvel/X-Men - Days of Future Past (2014) #1.cbz")
    args = Namespace(source=tmp_path, dry_run=True, execute=False, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)
    out = buf.getvalue()
    assert "Marvel/X-Men - Days of Future Past (2014)/X-Men - Days of Future Past (2014) #001.cbz" in out
    assert "Marvel/ →" not in out  # the container itself is never renamed


def test_execute_files_loose_comic_into_series_subfolder(tmp_path):
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "marvel/X-Men - Days of Future Past (2014) #1.cbz")
    args = Namespace(source=tmp_path, dry_run=False, execute=True, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)

    moved = tmp_path / "marvel/X-Men - Days of Future Past (2014)/X-Men - Days of Future Past (2014) #001.cbz"
    assert moved.is_file()
    assert not (tmp_path / "marvel/X-Men - Days of Future Past (2014) #1.cbz").exists()
    assert (tmp_path / "marvel").is_dir()  # container kept its own name


def test_lowercase_dc_container_is_recognized(tmp_path):
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "dc/Batman Adventures (1992) #4.cbz")
    args = Namespace(source=tmp_path, dry_run=True, execute=False, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)
    out = buf.getvalue()
    assert "dc/Batman Adventures (1992)/" in out
    assert "dc/ →" not in out


def test_multiple_series_in_one_container_get_separate_folders(tmp_path):
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "Image/Walking Dead (2003) #1.cbz")
    make_cbz(tmp_path / "Image/Saga (2012) #1.cbz")
    args = Namespace(source=tmp_path, dry_run=False, execute=True, log=None, no_color=True)
    with contextlib.redirect_stdout(io.StringIO()):
        run(args)

    assert (tmp_path / "Image/Walking Dead (2003)/Walking Dead (2003) #001.cbz").is_file()
    assert (tmp_path / "Image/Saga (2012)/Saga (2012) #001.cbz").is_file()


def test_unparseable_loose_file_stays_manual(tmp_path):
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "Marvel/Some Comic.cbr")
    args = Namespace(source=tmp_path, dry_run=True, execute=False, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)
    out = buf.getvalue()
    assert "loose file at publisher root `Marvel`" in out
    assert "couldn't infer a series folder" in out
    assert "moves=0" in out


def test_top_level_series_folder_with_year_is_not_a_container(tmp_path):
    """A proper `Series (Year)` folder at the source root keeps rename semantics."""
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "Aquaman Vol. 5 (1994)/Aquaman v5 000 (1994).cbz")
    args = Namespace(source=tmp_path, dry_run=True, execute=False, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)
    out = buf.getvalue()
    assert "Aquaman Vol. 5 (1994)/ → Aquaman (1994)/" in out
    assert "moves=" not in out or "moves=0" in out


def test_source_root_loose_file_moved_not_root_renamed(tmp_path):
    """A file loose directly in the library root never renames the root."""
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "Hawkeye (1983) #1.cbz")
    args = Namespace(source=tmp_path, dry_run=True, execute=False, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)
    out = buf.getvalue()
    assert f"{tmp_path.name}/ →" not in out
    assert "Hawkeye (1983)/Hawkeye (1983) #001.cbz" in out


def test_numberless_one_shot_gets_clean_series_name(tmp_path):
    """`Series (Year) GetComics.INFO.cbr` → `Series (Year)/Series (Year).cbr`."""
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "Marvel/X-Men - Days of Future Past (2014) GetComics.INFO.cbz")
    args = Namespace(source=tmp_path, dry_run=False, execute=True, log=None, no_color=True)
    with contextlib.redirect_stdout(io.StringIO()):
        run(args)

    moved = tmp_path / "Marvel/X-Men - Days of Future Past (2014)/X-Men - Days of Future Past (2014).cbz"
    assert moved.is_file()


def test_junk_filename_inside_canonical_folder_renamed_in_place(tmp_path):
    """Already-filed one-shot gets its filename scrubbed without moving."""
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "Marvel/X-Men - Days of Future Past (2014)/X-Men - Days of Future Past (2014) GetComics.INFO.cbz")
    args = Namespace(source=tmp_path, dry_run=False, execute=True, log=None, no_color=True)
    with contextlib.redirect_stdout(io.StringIO()):
        run(args)

    assert (tmp_path / "Marvel/X-Men - Days of Future Past (2014)/X-Men - Days of Future Past (2014).cbz").is_file()
    assert not (tmp_path / "Marvel/X-Men - Days of Future Past (2014)/X-Men - Days of Future Past (2014) GetComics.INFO.cbz").exists()


def test_collection_one_shot_in_canonical_folder_keeps_name(tmp_path):
    """Collections (omnibus/TPB/etc.) are never stripped to bare series names."""
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    src = tmp_path / "Marvel/Hawkeye Omnibus (2015)/Hawkeye Omnibus (2015).cbz"
    make_cbz(src)
    args = Namespace(source=tmp_path, dry_run=False, execute=True, log=None, no_color=True)
    with contextlib.redirect_stdout(io.StringIO()):
        run(args)

    assert src.is_file()  # untouched


def test_collection_without_volume_keeps_filename_when_moved(tmp_path):
    """A collection with no volume number keeps its distinguishing filename."""
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "Marvel/Hawkeye Omnibus (2015).cbz")
    args = Namespace(source=tmp_path, dry_run=False, execute=True, log=None, no_color=True)
    with contextlib.redirect_stdout(io.StringIO()):
        run(args)

    assert (tmp_path / "Marvel/Hawkeye Omnibus (2015)/Hawkeye Omnibus (2015).cbz").is_file()


def test_umbrella_volume_wrapper_collapses(tmp_path):
    """Marvel/Hawkeye/Volume 01 (1994)/ collapses to Marvel/Hawkeye (1994)/."""
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    for n in range(1, 5):
        make_cbz(tmp_path / f"Marvel/Hawkeye/Volume 01 (1994)/Hawkeye (1994) #{n:03d}.cbz")
    args = Namespace(source=tmp_path, dry_run=False, execute=True, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)

    dest = tmp_path / "Marvel/Hawkeye (1994)"
    for n in range(1, 5):
        assert (dest / f"Hawkeye (1994) #{n:03d}.cbz").is_file()
    assert not (tmp_path / "Marvel/Hawkeye").exists()  # wrappers pruned
    out = buf.getvalue()
    assert "manual=0" in out
    assert "pruned=2" in out


def test_umbrella_collapse_merges_into_existing_series_folder(tmp_path):
    """Collapsing into an already-existing series folder skips collisions."""
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz")  # pre-existing
    make_cbz(tmp_path / "Marvel/Hawkeye/Volume 01 (1994)/Hawkeye (1994) #001.cbz")
    args = Namespace(source=tmp_path, dry_run=True, execute=False, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)
    assert "SKIP (dest exists)" in buf.getvalue()


def test_unparseable_deep_wrapper_stays_manual(tmp_path):
    """Deep wrapper + unparseable filename still reports manual."""
    import contextlib
    import io
    from argparse import Namespace
    from comicmeta._commands.organize import run

    make_cbz(tmp_path / "Marvel/Hawkeye/Volume 01 (1994)/Some Comic.cbr")
    args = Namespace(source=tmp_path, dry_run=True, execute=False, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)
    out = buf.getvalue()
    assert "umbrella wrapper 'Marvel/Hawkeye'" in out
    assert "couldn't infer series/year" in out
