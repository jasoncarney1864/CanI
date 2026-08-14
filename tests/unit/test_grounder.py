from cani_shared.models import Verdict, VerdictKind
from cani_shared.providers.grounder import ContextChunk, FakeGrounder, extract_verdict


def _doc_chunk(text: str) -> ContextChunk:
    return ContextChunk(text=text, source_label='your document "Test Doc"', source_kind="user_document")


def _law_chunk(text: str, source_label: str = "NRS 116.31065 (Nevada state law)") -> ContextChunk:
    return ContextChunk(text=text, source_label=source_label, source_kind="state_statute")


def test_extract_verdict_pulls_marker_and_cleans_text():
    kind, cleaned = extract_verdict("[verdict:no] You are not permitted to do this.")
    assert kind == "no"
    assert cleaned == "You are not permitted to do this."


def test_extract_verdict_prefers_multiword_kind():
    kind, cleaned = extract_verdict("[verdict:yes_with_conditions] Allowed if painted.")
    assert kind == "yes_with_conditions"
    assert "verdict" not in cleaned


def test_extract_verdict_is_case_insensitive():
    kind, _ = extract_verdict("[VERDICT: Yes] fine")
    assert kind == "yes"


def test_extract_verdict_absent_returns_none_and_original_text():
    kind, cleaned = extract_verdict("The quiet hours begin at 10pm.")
    assert kind is None
    assert cleaned == "The quiet hours begin at 10pm."


def test_fake_grounder_emits_verdict_for_yes_no_question():
    grounded = FakeGrounder().ground(
        question="Can I build a shed?", context_chunks=[_doc_chunk("Sheds are permitted in rear yards.")]
    )
    assert grounded.verdict == "yes_with_conditions"


def test_fake_grounder_omits_verdict_for_open_ended_question():
    grounded = FakeGrounder().ground(
        question="When must dogs be leashed?",
        context_chunks=[_doc_chunk("Dogs must be leashed at all times.")],
    )
    assert grounded.verdict is None


def test_fake_grounder_reports_insufficient_verdict_without_context():
    grounded = FakeGrounder().ground(question="Can I park here?", context_chunks=[])
    assert grounded.insufficient_evidence is True
    assert grounded.verdict == "insufficient"


def test_verdict_from_kind_derives_label():
    verdict = Verdict.from_kind("yes_with_conditions")
    assert verdict.kind is VerdictKind.YES_WITH_CONDITIONS
    assert verdict.label == "Yes, with conditions"


def test_fake_grounder_document_only_context_unchanged_from_baseline():
    # Pure document context must keep behaving exactly as it did before ContextChunk
    # existed — this is the case the original e2e test asserts against.
    grounded = FakeGrounder().ground(
        question="When must dogs be leashed?", context_chunks=[_doc_chunk("Dogs must be leashed at 9pm.")]
    )
    assert grounded.answer_text == "Based on your document [chunk:0]: Dogs must be leashed at 9pm."
    assert grounded.used_chunk_indices == [0]


def test_fake_grounder_quote_pairs_law_chunks():
    quote = "Must be reasonably related to the purpose for which they are adopted."
    grounded = FakeGrounder().ground(
        question="Are HOA rules required to relate to their purpose?",
        context_chunks=[
            _doc_chunk("The board may adopt reasonable rules."),
            _law_chunk(quote),
        ],
    )
    assert quote in grounded.answer_text
    assert "NRS 116.31065 (Nevada state law)" in grounded.answer_text
    assert "What your document says" in grounded.answer_text
    assert "What the governing law says" in grounded.answer_text
    assert grounded.used_chunk_indices == [0, 1]


def test_fake_grounder_quote_pairs_law_only_context():
    quote = "Sheds are permitted in rear yards."
    grounded = FakeGrounder().ground(
        question="Can I build a shed?",
        context_chunks=[_law_chunk(quote, source_label="NRS 116.001 (Nevada state law)")],
    )
    assert quote in grounded.answer_text
    assert "What your document says" not in grounded.answer_text
    assert grounded.used_chunk_indices == [0]


def test_build_user_prompt_labels_each_chunk():
    from cani_shared.providers.grounder import _build_user_prompt

    prompt = _build_user_prompt(
        "question?",
        [_doc_chunk("doc text"), _law_chunk("law text", source_label="NRS 116.001 (Nevada state law)")],
    )
    assert '[chunk:0 | your document "Test Doc"] doc text' in prompt
    assert "[chunk:1 | NRS 116.001 (Nevada state law)] law text" in prompt
