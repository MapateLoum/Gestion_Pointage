import hashlib

import pytest

from app.biometrics.face import engine as engine_module
from app.biometrics.face.engine import ModelDownloadError, ModelFile, OpenCVFaceEngine, ensure_models
from app.biometrics.face.types import EngineNotReady


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(engine_module, "RETRY_DELAY", 0)


def make_model(tmp_path, name="m.onnx", content=b"contenu-du-modele", good_first=True):
    source = tmp_path / "src" / name
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(content)
    missing = (tmp_path / "src" / "absent.onnx").as_uri()
    urls = (source.as_uri(),) if good_first else (missing, source.as_uri())
    return ModelFile(name=name, sha256=hashlib.sha256(content).hexdigest(), urls=urls), source


def test_download_is_verified_and_cached(tmp_path):
    model, source = make_model(tmp_path)
    dest = tmp_path / "models"
    (path,) = ensure_models(dest, (model,))
    assert path.read_bytes() == b"contenu-du-modele"
    source.unlink()  # déjà présent et vérifié : pas de nouveau téléchargement
    assert ensure_models(dest, (model,)) == [path]


def test_falls_back_to_second_url(tmp_path):
    model, _ = make_model(tmp_path, good_first=False)
    (path,) = ensure_models(tmp_path / "models", (model,))
    assert path.exists()


def test_corrupted_download_is_rejected_and_not_kept(tmp_path):
    model, _ = make_model(tmp_path)
    wrong = ModelFile(name=model.name, sha256="0" * 64, urls=model.urls)
    dest = tmp_path / "models"
    with pytest.raises(ModelDownloadError, match="SHA-256"):
        ensure_models(dest, (wrong,))
    assert list(dest.iterdir()) == []  # ni fichier final ni fichier partiel


def test_existing_file_with_wrong_content_is_not_overwritten(tmp_path):
    model, _ = make_model(tmp_path)
    dest = tmp_path / "models"
    dest.mkdir()
    (dest / model.name).write_bytes(b"autre chose")
    with pytest.raises(ModelDownloadError, match="ne correspond pas"):
        ensure_models(dest, (model,))
    assert (dest / model.name).read_bytes() == b"autre chose"


def test_engine_reports_loading_failure_clearly(tmp_path):
    bad = ModelFile(name="x.onnx", sha256="0" * 64, urls=((tmp_path / "nope").as_uri(),))
    engine = OpenCVFaceEngine(str(tmp_path / "models"), models=(bad, bad))
    assert engine.status().state == "idle"
    engine.load()
    status = engine.status()
    assert status.state == "error" and "Téléchargement impossible" in status.error
    with pytest.raises(EngineNotReady, match="n'a pas pu démarrer"):
        engine.analyze(__import__("numpy").zeros((10, 10, 3), dtype="uint8"))
