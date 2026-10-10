from pathlib import Path


def test_api_base_installs_retrieval_without_document_inference():
    dockerfile = (Path(__file__).parents[3] / "Dockerfile").read_text()
    base = dockerfile.split("FROM base AS with-aws", 1)[0]
    assert "uv sync --locked --no-dev --extra document-retrieval" in base
    assert "--extra document-processing" not in base
    assert "fonts-noto-cjk" not in base
