import pytest

from tars import cuda


def test_missing_libs_are_named(tmp_path, monkeypatch):
    monkeypatch.setattr(cuda, "NVIDIA", tmp_path)
    monkeypatch.delenv("TARS_CUDA_LIBS", raising=False)
    (tmp_path / "cudnn" / "lib").mkdir(parents=True)
    (tmp_path / "cudnn" / "lib" / "libcudnn.so.9").touch()
    assert cuda.missing_libs() == ["libcudart.so.12", "libcublas.so.12"]
    with pytest.raises(SystemExit, match="libcudart.so.12, libcublas.so.12"):
        cuda.reexec_with_cuda_libs("tars.voice")
