import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest


def test_native_remote_vlm_without_local_models():
    pytest.importorskip("docling")
    import pypdfium2 as pdfium
    from langboard_shared.tasks.docling.DocumentVision import create_vision_converter

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(payload)
            body = json.dumps(
                {
                    "id": "native-probe",
                    "created": 1,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '# Native remote conversion\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n<!--LANGBOARD_SEARCH_KEYWORDS:{"ko":["문서 검색"],"en":["document search"],"ja":["文書検索"],"zh":["文档搜索"]}-->',
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"completion_tokens": 40, "prompt_tokens": 100, "total_tokens": 140},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    progress = []
    keywords = []
    converter = create_vision_converter(
        json.dumps({"base_url": base, "model_name": "vision-test"}),
        {base},
        on_progress=lambda current, total: progress.append((current, total)),
        on_keywords=lambda page, attributes: keywords.append((page, attributes)),
    )
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "two-pages.pdf"
        with pdfium.PdfDocument.new() as document:
            for _ in range(2):
                document.new_page(200, 200).close()
            document.save(path)
        result = converter.convert(path)
        markdown = result.document.export_to_markdown()
        assert len(seen) == 2, (len(seen), result.status)
        assert progress == [(0, 2), (1, 2), (2, 2)]
        assert len(keywords) == 2
        assert keywords[0][1] == {
            "ko": ["문서 검색"],
            "en": ["document search"],
            "ja": ["文書検索"],
            "zh": ["文档搜索"],
        }
        assert "LANGBOARD_SEARCH_KEYWORDS" not in markdown
        assert "문서 검색" not in markdown
        assert all(p["model"] == "vision-test" for p in seen)
        assert all(any(c["type"] == "image_url" for c in p["messages"][0]["content"]) for p in seen)
        assert "Native remote conversion" in markdown and len(result.document.tables) == 2, markdown
        assert result.document.export_to_dict()["schema_name"] == "DoclingDocument"
        assert importlib.util.find_spec("torch") is None
        print(
            json.dumps(
                {
                    "status": str(result.status),
                    "requests": len(seen),
                    "docling_document": True,
                    "markdown_table": True,
                    "torch_installed": False,
                }
            )
        )
    server.shutdown()

    with pytest.raises(ValueError, match="approved"):
        create_vision_converter(json.dumps({"base_url": base, "model_name": "vision-test"}), set())


def test_korean_unembedded_font_renders_when_worker_fonts_are_installed():
    import os

    if os.environ.get("VERIFY_DOCUMENT_FONTS") != "1":
        pytest.skip("Document worker font installation is required")
    import pypdfium2 as pdfium

    source = Path(__file__).parent / "fixtures" / "korean-unembedded.pdf"
    with pdfium.PdfDocument(source) as document:
        page = document[0]
        assert "한글 문서 검증" in page.get_textpage().get_text_range()
        image = page.render(scale=2).to_pil().convert("L")
        # This region is blank without Korean fallback glyphs although text extraction succeeds.
        crop = image.crop((40, 60, 680, 150))
        assert sum(pixel < 128 for pixel in crop.getdata()) > 1000
