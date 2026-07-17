from cani_shared.models import Verdict, VerdictKind
from cani_shared.providers.grounder import FakeGrounder, extract_verdict


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
        question="Can I build a shed?", context_chunks=["Sheds are permitted in rear yards."]
    )
    assert grounded.verdict == "yes_with_conditions"


def test_fake_grounder_omits_verdict_for_open_ended_question():
    grounded = FakeGrounder().ground(
        question="When must dogs be leashed?", context_chunks=["Dogs must be leashed at all times."]
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
