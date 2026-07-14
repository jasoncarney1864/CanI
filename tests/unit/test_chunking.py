from cani_shared.chunking import PageText, chunk_document


def _sample_pages() -> list[PageText]:
    body_line = "This clause describes the leash policy for common areas. " * 20
    return [
        PageText(page_number=1, text=f"1. LEASH POLICY\n{body_line}\n{body_line}"),
        PageText(page_number=2, text=f"2. QUIET HOURS\n{body_line}\n{body_line}"),
    ]


def test_chunking_is_deterministic():
    pages = _sample_pages()
    first = chunk_document(pages)
    second = chunk_document(pages)
    assert [c.text for c in first] == [c.text for c in second]


def test_chunks_have_page_bounds_and_metadata():
    chunks = chunk_document(_sample_pages())
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.page_start <= chunk.page_end
        assert chunk.token_count > 0
        assert chunk.text.strip()


def test_chunk_indices_are_sequential():
    chunks = chunk_document(_sample_pages())
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_section_labels_detected():
    chunks = chunk_document(_sample_pages())
    labels = {c.section_label for c in chunks if c.section_label}
    assert any("LEASH POLICY" in label for label in labels)
