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
