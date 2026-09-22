from gmagc_desktop.service.corrections import Correction, load_corrections, new_correction, save_corrections


def test_a_missing_file_gives_an_empty_list(tmp_path):
    assert load_corrections(tmp_path / "corrections.json") == []


def test_a_corrupted_file_gives_an_empty_list(tmp_path):
    path = tmp_path / "corrections.json"
    path.write_text("не json совсем", encoding="utf-8")

    assert load_corrections(path) == []


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "corrections.json"
    corrections = [new_correction("vendor/wrong.png", "vendor/right.png", now=1000.0)]

    save_corrections(corrections, path)

    assert load_corrections(path) == corrections


def test_a_record_missing_a_field_is_skipped_but_the_rest_still_load(tmp_path):
    path = tmp_path / "corrections.json"
    path.write_text(
        '[{"wrong": "a.png", "correct": "b.png", "created_at": 1.0}, {"wrong": "only wrong"}]', encoding="utf-8"
    )

    assert load_corrections(path) == [Correction("a.png", "b.png", 1.0)]


def test_new_correction_defaults_to_now():
    before = new_correction("a", "b")
    assert before.wrong_rel_path == "a" and before.correct_rel_path == "b" and before.created_at > 0
