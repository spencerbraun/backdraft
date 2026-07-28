"""Reading claims out of authored markdown."""

from __future__ import annotations

from backdraft.kernel.claims import parse_citation, parse_claims
from backdraft.kernel.model import CitationStatus

TOKEN = "bd:t12-audit:p8.c3:a7f3"
OTHER = "bd:model:rent-roll!B10:9e2f"


def test_single_claim() -> None:
    source = f"The [DSCR of 1.42x]({TOKEN}) clears the covenant."
    (claim,) = parse_claims(source)
    assert claim.text == "DSCR of 1.42x"
    assert source[claim.start : claim.end] == f"[DSCR of 1.42x]({TOKEN})"
    assert [c.token for c in claim.citations] == [TOKEN]
    assert claim.citations[0].status is CitationStatus.UNRESOLVED
    assert claim.citations[0].error is None
    assert claim.unmatched is False


def test_multiple_citations_on_one_claim() -> None:
    source = f"[NOI ties out]({TOKEN};{OTHER})"
    (claim,) = parse_claims(source)
    assert [c.token for c in claim.citations] == [TOKEN, OTHER]
    assert all(c.status is CitationStatus.UNRESOLVED for c in claim.citations)


def test_citations_may_be_spaced_around_the_separator() -> None:
    (claim,) = parse_claims(f"[x]({TOKEN} ; {OTHER})")
    assert [c.token for c in claim.citations] == [TOKEN, OTHER]


def test_claims_are_in_document_order() -> None:
    source = f"[one]({TOKEN}) then [two]({OTHER}) then [three]({TOKEN})"
    claims = parse_claims(source)
    assert [c.text for c in claims] == ["one", "two", "three"]
    assert [c.start for c in claims] == sorted(c.start for c in claims)
    for claim in claims:
        assert source[claim.start] == "["
        assert source[claim.end - 1] == ")"


def test_no_claims() -> None:
    assert parse_claims("Just prose, no links at all.") == []
    assert parse_claims("") == []


def test_non_bd_links_are_ignored() -> None:
    source = (
        "See [the docs](https://example.com) and [an anchor](#section) "
        f"and [a file](./notes.md) and [a claim]({TOKEN})."
    )
    claims = parse_claims(source)
    assert [c.text for c in claims] == ["a claim"]


def test_empty_href_is_ignored() -> None:
    assert parse_claims("[not a claim]()") == []


def test_images_are_not_claims() -> None:
    assert parse_claims(f"![alt text]({TOKEN})") == []


def test_claim_inside_other_formatting() -> None:
    source = (
        f"- **Bold [claim one]({TOKEN})** and _italic [claim two]({OTHER})_\n"
        f"> quoted [claim three]({TOKEN})\n"
        f"### Heading with [claim four]({OTHER})\n"
    )
    assert [c.text for c in parse_claims(source)] == [
        "claim one",
        "claim two",
        "claim three",
        "claim four",
    ]


def test_multiline_claim_text() -> None:
    source = f"[a claim that wraps\nacross two lines]({TOKEN})"
    (claim,) = parse_claims(source)
    assert claim.text == "a claim that wraps\nacross two lines"
    assert source[claim.start : claim.end].endswith(f"({TOKEN})")


def test_nested_brackets_in_claim_text() -> None:
    source = f"[the value [B10] as reported]({TOKEN})"
    (claim,) = parse_claims(source)
    assert claim.text == "the value [B10] as reported"


def test_nested_link_in_claim_text() -> None:
    source = f"[outer [inner]({OTHER}) tail]({TOKEN})"
    claims = parse_claims(source)
    assert [c.text for c in claims] == ["outer [inner]({}) tail".format(OTHER)]
    assert [c.token for c in claims[0].citations] == [TOKEN]


def test_inner_link_is_found_when_the_outer_bracket_is_not_a_link() -> None:
    source = f"[bracketed text with [a claim]({TOKEN}) inside]"
    assert [c.text for c in parse_claims(source)] == ["a claim"]


def test_escaped_brackets_do_not_open_a_link() -> None:
    source = f"\\[not a link\\]({TOKEN}) but [this is]({OTHER})"
    assert [c.text for c in parse_claims(source)] == ["this is"]


def test_unbalanced_brackets_do_not_crash() -> None:
    assert parse_claims(f"[unclosed {TOKEN}") == []
    assert parse_claims(f"[text]({TOKEN}") == []
    assert parse_claims("](" + TOKEN + ")") == []
    assert parse_claims("[") == []
    assert parse_claims("\\") == []


def test_link_title_is_dropped() -> None:
    (claim,) = parse_claims(f'[x]({TOKEN} "why this matters")')
    assert [c.token for c in claim.citations] == [TOKEN]


def test_angle_bracket_href() -> None:
    (claim,) = parse_claims(f"[x](<{TOKEN}>)")
    assert [c.token for c in claim.citations] == [TOKEN]


# --- malformed citations are reported, never raised --------------------------


def test_malformed_token_yields_a_malformed_citation() -> None:
    (claim,) = parse_claims("[claim](bd:BADSLUG:p8:zzzz)")
    citation = claim.citations[0]
    assert citation.status is CitationStatus.MALFORMED
    assert citation.token == "bd:BADSLUG:p8:zzzz"
    assert citation.error


def test_malformed_token_is_reported_verbatim_whitespace_and_all() -> None:
    (claim,) = parse_claims("[claim](bd:BAD SLUG:p8:zzzz)")
    citation = claim.citations[0]
    assert citation.status is CitationStatus.MALFORMED
    assert citation.token == "bd:BAD SLUG:p8:zzzz"


def test_partly_malformed_href_keeps_both_citations() -> None:
    source = f"[claim]({TOKEN};bd:oops)"
    (claim,) = parse_claims(source)
    assert [c.status for c in claim.citations] == [
        CitationStatus.UNRESOLVED,
        CitationStatus.MALFORMED,
    ]


def test_non_bd_piece_alongside_a_token_is_malformed_not_dropped() -> None:
    source = f"[claim]({TOKEN};https://example.com)"
    (claim,) = parse_claims(source)
    assert [c.token for c in claim.citations] == [TOKEN, "https://example.com"]
    assert claim.citations[1].status is CitationStatus.MALFORMED


def test_stray_separators_do_not_invent_citations() -> None:
    (claim,) = parse_claims(f"[claim]({TOKEN};)")
    assert len(claim.citations) == 1


def test_reserved_derivation_is_surfaced_as_unsupported() -> None:
    source = "[the numbers tie](bd:calc(model:rent-roll!B10 / t12-audit:p4.c1))"
    (claim,) = parse_claims(source)
    citation = claim.citations[0]
    assert citation.status is CitationStatus.MALFORMED
    assert citation.token == "bd:calc(model:rent-roll!B10 / t12-audit:p4.c1)"
    assert "not supported" in (citation.error or "")
    assert "bd:calc" in (citation.error or "")


def test_parse_citation_is_total() -> None:
    for text in ("", "bd:", "bd:calc(", "nonsense", TOKEN):
        citation = parse_citation(text)
        assert citation.token == text
        assert citation.status in (CitationStatus.UNRESOLVED, CitationStatus.MALFORMED)


def test_offsets_cover_the_rewritable_construct() -> None:
    source = f"Intro. [claim text]({TOKEN}) outro."
    (claim,) = parse_claims(source)
    rewritten = source[: claim.start] + f"[{claim.text}](#cite-1)" + source[claim.end :]
    assert rewritten == "Intro. [claim text](#cite-1) outro."
