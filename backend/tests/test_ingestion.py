"""File validation, parsing, chunking and the upload/ingestion/delete lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.chunking import chunk_document, make_chunk_id
from app.rag.loaders import DocumentLoadError, LoadedDocument, LoadedPage, load_document
from app.utils.file_validation import (
    FileValidationError,
    sanitize_filename,
    validate_content_header,
    validate_filename,
)
from app.utils.text_processing import clean_text
from tests.conftest import make_settings, minimal_pdf

# ---------------------------------------------------------------------- file validation


@pytest.mark.parametrize("name", ["report.pdf", "notes.TXT", "guide.md", "x.markdown"])
def test_allowed_extensions(name):
    assert validate_filename(name).extension in {".pdf", ".txt", ".md", ".markdown"}


@pytest.mark.parametrize("name", ["evil.exe", "script.js", "archive.zip", "noext", "doc.pdf.exe"])
def test_unsupported_extensions_rejected(name):
    with pytest.raises(FileValidationError):
        validate_filename(name)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("../../etc/passwd.txt", "passwd.txt"),
        ("..\\..\\windows\\system32\\a.md", "a.md"),
        ("/abs/path/file.pdf", "file.pdf"),
        ("we<ird>na:me?.txt", "we_ird_na_me_.txt"),
    ],
)
def test_filenames_are_sanitized(raw, expected):
    assert sanitize_filename(raw) == expected


def test_missing_filename_rejected():
    with pytest.raises(FileValidationError):
        sanitize_filename("")


def test_pdf_magic_bytes_required():
    validate_content_header(b"%PDF-1.7 ...", "pdf")
    with pytest.raises(FileValidationError, match="valid PDF"):
        validate_content_header(b"MZ\x90\x00 not a pdf", "pdf")


def test_binary_text_rejected():
    with pytest.raises(FileValidationError, match="binary"):
        validate_content_header(b"hello\x00world", "text")


def test_non_utf8_text_rejected():
    with pytest.raises(FileValidationError, match="UTF-8"):
        validate_content_header("café".encode("latin-1") + b" more text here", "text")


def test_empty_content_rejected():
    with pytest.raises(FileValidationError, match="empty"):
        validate_content_header(b"", "markdown")


# ---------------------------------------------------------------------- parsing


def test_clean_text_preserves_structure():
    raw = "Title\r\n\r\n\r\n\r\nPara  one   with  spaces.\nhyphen-\nated word\x07"
    out = clean_text(raw)
    assert "Title\n\nPara one with spaces." in out
    assert "hyphenated" in out
    assert "\x07" not in out


def test_pdf_text_and_page_numbers(tmp_path: Path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(
        minimal_pdf(["Alpha page talks about retrieval.", "Beta page covers reranking."])
    )
    doc = load_document(path, "pdf")
    assert doc.page_count == 2
    assert [p.page_number for p in doc.pages] == [1, 2]
    assert "retrieval" in doc.pages[0].text and "reranking" in doc.pages[1].text


def test_scanned_pdf_reports_ocr_not_configured(tmp_path: Path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(minimal_pdf(["", ""]))
    with pytest.raises(DocumentLoadError, match="OCR is not configured"):
        load_document(path, "pdf")


def test_corrupt_pdf_rejected(tmp_path: Path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is not really a pdf")
    with pytest.raises(DocumentLoadError):
        load_document(path, "pdf")


def test_empty_text_document_rejected(tmp_path: Path):
    path = tmp_path / "empty.txt"
    path.write_text("   \n\n  \t ", encoding="utf-8")
    with pytest.raises(DocumentLoadError, match="empty"):
        load_document(path, "text")


def test_markdown_loaded_without_page_numbers(tmp_path: Path):
    path = tmp_path / "a.md"
    path.write_text("# Heading\n\nSome markdown body text that is long enough.", encoding="utf-8")
    doc = load_document(path, "markdown")
    assert doc.page_count is None and doc.pages[0].page_number is None


# ---------------------------------------------------------------------- chunking


def _doc(text: str, page: int | None = None) -> LoadedDocument:
    return LoadedDocument(pages=[LoadedPage(text=text, page_number=page)], page_count=None)


def test_chunks_respect_size_and_overlap():
    text = " ".join(f"word{i}" for i in range(600))
    chunks = chunk_document(
        _doc(text), document_id="d1", file_type="text", chunk_size=200, chunk_overlap=40
    )
    assert len(chunks) > 5
    assert all(len(c.text) <= 200 for c in chunks)
    # Overlap: the tail of one chunk reappears at the start of the next.
    assert chunks[0].text.split()[-1] in chunks[1].text


def test_chunk_ids_are_deterministic_and_unique():
    text = "sentence. " * 200
    a = chunk_document(
        _doc(text), document_id="doc", file_type="text", chunk_size=150, chunk_overlap=20
    )
    b = chunk_document(
        _doc(text), document_id="doc", file_type="text", chunk_size=150, chunk_overlap=20
    )
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert len({c.chunk_id for c in a}) == len(a)
    assert a[0].chunk_id == make_chunk_id("doc", 0)
    assert [c.chunk_index for c in a] == list(range(len(a)))


def test_pages_chunked_separately_keep_page_numbers():
    doc = LoadedDocument(
        pages=[LoadedPage("page one " * 50, 1), LoadedPage("page two " * 50, 2)], page_count=2
    )
    chunks = chunk_document(doc, document_id="d", file_type="pdf", chunk_size=120, chunk_overlap=10)
    assert {c.page_number for c in chunks} == {1, 2}
    assert all(("one" in c.text) == (c.page_number == 1) for c in chunks)


def test_markdown_prefers_heading_boundaries():
    md = "# A\n" + "alpha text. " * 15 + "\n## B\n" + "beta text. " * 15
    chunks = chunk_document(
        _doc(md), document_id="d", file_type="markdown", chunk_size=220, chunk_overlap=0
    )
    assert any(c.text.startswith("## B") for c in chunks)


# ---------------------------------------------------------------------- API lifecycle


async def upload(client, files, wait=True):
    return await client.post(
        "/api/v1/documents/upload", params={"wait": str(wait).lower()}, files=files
    )


async def test_upload_index_list_get_delete(client, sample_corpus, embedder):
    r = await upload(client, [("files", ("platform_guide.md", sample_corpus, "text/markdown"))])
    assert r.status_code == 202, r.text
    res = r.json()["results"][0]
    assert res["outcome"] == "indexed", res
    doc = res["document"]
    assert doc["status"] == "indexed" and doc["chunk_count"] > 5
    assert doc["embedding_model"] == embedder.model
    doc_id = doc["document_id"]

    listing = (await client.get("/api/v1/documents")).json()
    assert listing["total"] == 1 and listing["items"][0]["document_id"] == doc_id

    got = (await client.get(f"/api/v1/documents/{doc_id}")).json()
    assert got["filename"] == "platform_guide.md"

    search = (
        await client.post("/api/v1/retrieval/search", json={"query": "default chunk size overlap"})
    ).json()
    assert search["reranked"] and search["reranked"][0]["document_id"] == doc_id

    d = await client.delete(f"/api/v1/documents/{doc_id}")
    assert d.status_code == 200 and d.json()["deleted"] is True
    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 404
    after = (
        await client.post("/api/v1/retrieval/search", json={"query": "default chunk size overlap"})
    ).json()
    assert (
        after["reranked"] == [] and after["dense_candidates"] == 0 and after["bm25_candidates"] == 0
    )


async def test_chunk_metadata_preserved_in_vector_store(client, container, sample_corpus):
    await upload(client, [("files", ("guide.md", sample_corpus, "text/markdown"))])
    points = [p async for p in container.vector_store.scroll_payloads()]
    assert points
    _, payload = points[0]
    for key in (
        "document_id",
        "filename",
        "chunk_id",
        "chunk_index",
        "page_number",
        "source",
        "content",
        "ingestion_timestamp",
        "content_hash",
        "embedding_model",
    ):
        assert key in payload, key
    assert payload["filename"] == "guide.md"


async def test_pdf_upload_records_pages(client):
    pdf = minimal_pdf(["The capital of Testland is Mockville.", "Mockville has a large library."])
    r = await upload(client, [("files", ("cities.pdf", pdf, "application/pdf"))])
    res = r.json()["results"][0]
    assert res["outcome"] == "indexed", res
    assert res["document"]["page_count"] == 2


async def test_multiple_files_report_per_file_results(client, sample_corpus):
    r = await upload(
        client,
        [
            ("files", ("ok.md", sample_corpus, "text/markdown")),
            ("files", ("bad.exe", b"MZ....", "application/octet-stream")),
            ("files", ("empty.txt", b"", "text/plain")),
            ("files", ("fake.pdf", b"not a pdf at all", "application/pdf")),
        ],
    )
    body = r.json()
    outcomes = {x["filename"]: x["outcome"] for x in body["results"]}
    assert outcomes == {
        "ok.md": "indexed",
        "bad.exe": "rejected",
        "empty.txt": "rejected",
        "fake.pdf": "rejected",
    }
    assert body["accepted"] == 1 and body["rejected"] == 3


async def test_duplicate_upload_detected(client, sample_corpus):
    first = await upload(client, [("files", ("a.md", sample_corpus, "text/markdown"))])
    second = await upload(client, [("files", ("copy.md", sample_corpus, "text/markdown"))])
    assert first.json()["results"][0]["outcome"] == "indexed"
    dup = second.json()["results"][0]
    assert dup["outcome"] == "duplicate"
    assert dup["document_id"] == first.json()["results"][0]["document_id"]
    assert (await client.get("/api/v1/documents")).json()["total"] == 1


async def test_empty_document_marked_failed(client):
    r = await upload(client, [("files", ("blank.txt", b"   \n\n   \n", "text/plain"))])
    res = r.json()["results"][0]
    assert res["outcome"] == "failed"
    assert "empty" in res["message"].lower()
    assert res["document"]["status"] == "failed"


async def test_failed_document_can_be_retried(
    client, container, embedder, monkeypatch, sample_corpus
):
    async def broken(texts):
        from app.core.exceptions import UpstreamRateLimited

        raise UpstreamRateLimited("OpenAI rate limit hit during embedding; retry later.")

    monkeypatch.setattr(container.documents.embedder, "embed_documents", broken)
    first = (await upload(client, [("files", ("g.md", sample_corpus, "text/markdown"))])).json()[
        "results"
    ][0]
    assert first["outcome"] == "failed" and "rate limit" in first["message"]
    monkeypatch.undo()
    retry = (await upload(client, [("files", ("g.md", sample_corpus, "text/markdown"))])).json()[
        "results"
    ][0]
    assert retry["outcome"] == "indexed"
    assert retry["document_id"] == first["document_id"]


async def test_oversized_upload_rejected(tmp_path, embedder, generator, scorer):
    import httpx

    from app.main import create_app
    from tests.conftest import build_container

    settings = make_settings(tmp_path, max_upload_size_mb=1)
    app = create_app(settings, build_container(settings, embedder, generator, scorer))
    big = b"a" * (1024 * 1024 + 10)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        r = await upload(c, [("files", ("big.txt", big, "text/plain"))])
    res = r.json()["results"][0]
    assert res["outcome"] == "rejected" and "1 MB" in res["message"]
    # No temp files left behind.
    assert not list((settings.upload_tmp_dir).glob("*"))


async def test_too_many_files_rejected(client):
    files = [("files", (f"f{i}.txt", b"hello world text", "text/plain")) for i in range(11)]
    r = await upload(client, files)
    assert r.status_code == 422


async def test_upload_without_files_rejected(client):
    r = await client.post("/api/v1/documents/upload")
    assert r.status_code == 422


async def test_background_ingestion_status_transitions(client, container, sample_corpus):
    r = await upload(client, [("files", ("bg.md", sample_corpus, "text/markdown"))], wait=False)
    res = r.json()["results"][0]
    assert res["outcome"] == "accepted"
    doc_id = res["document_id"]
    # Wait for the background task to finish.
    import asyncio

    for _ in range(100):
        status = (await client.get(f"/api/v1/ingestion/status/{doc_id}")).json()["status"]
        if status in {"indexed", "failed"}:
            break
        await asyncio.sleep(0.05)
    assert status == "indexed"


async def test_interrupted_ingestion_marked_failed_on_startup(container):
    await container.store.create_document(
        {
            "document_id": "stuck",
            "filename": "x.md",
            "file_type": "markdown",
            "size_bytes": 1,
            "content_hash": "h",
            "status": "processing",
        }
    )
    await container.startup()
    doc = await container.store.get_document("stuck")
    assert doc["status"] == "failed" and "restart" in doc["error"]
