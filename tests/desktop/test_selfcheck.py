from gmagc_desktop.selfcheck import run_core_check


def test_core_check_runs_the_pipeline_and_reports_versions():
    info = run_core_check()

    assert info["ok"] is True
    assert info["shape"] == (224, 224)
    assert set(info["versions"]) == {"python", "numpy", "opencv"}
    assert all(info["versions"].values())
