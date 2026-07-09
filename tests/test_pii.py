from agent.config import load_settings
from agent.safety.pii import mask_rows, mask_text

settings = load_settings()


def test_denylisted_column_masked_case_insensitively():
    rows = [{"EMAIL": "jane@example.com"}, {"Email": "bob@shop.io"}]
    masked, hits = mask_rows(rows, settings)
    assert masked[0]["EMAIL"] == "«email masked»"
    assert masked[1]["Email"] == "«email masked»"
    assert hits == 2


def test_alias_evasion_caught_by_value_sweep():
    rows = [{"contact_info": "reach jane@example.com anytime"}]
    masked, hits = mask_rows(rows, settings)
    assert "jane@example.com" not in masked[0]["contact_info"]
    assert "«email masked»" in masked[0]["contact_info"]
    assert hits == 1


def test_phone_formats_masked():
    rows = [{"note": "call (415) 555-2671 or 415-555-2671 or +14155552671"}]
    masked, hits = mask_rows(rows, settings)
    assert "415" not in masked[0]["note"]
    assert hits == 3


def test_numbers_that_are_not_phones_survive():
    rows = [
        {"avg_price": "158.9724"},
        {"longitude": "-115.170563"},
        {"date": "2026-07-09"},
        {"order_id": "4155552671"},
    ]
    masked, hits = mask_rows(rows, settings)
    assert hits == 0
    assert masked[0]["avg_price"] == "158.9724"
    assert masked[3]["order_id"] == "4155552671"


def test_non_string_values_untouched():
    rows = [{"revenue": 187539.19, "orders": 12, "returned_at": None}]
    masked, hits = mask_rows(rows, settings)
    assert masked[0] == rows[0]
    assert hits == 0


def test_null_in_denylisted_column_not_counted():
    rows = [{"email": None}]
    masked, hits = mask_rows(rows, settings)
    assert masked[0]["email"] is None
    assert hits == 0


def test_masking_is_idempotent():
    rows = [{"email": "jane@example.com", "note": "call 415-555-2671"}]
    once, _ = mask_rows(rows, settings)
    twice, second_hits = mask_rows(once, settings)
    assert second_hits >= 1  # denylisted column re-masks its placeholder
    assert twice[0]["note"] == once[0]["note"]  # sweep finds nothing new


def test_output_sweep_masks_answer_text():
    text = "Top customer: Jane Doe (jane.doe+vip@example.co.uk, +1 415 555 2671)."
    masked, hits = mask_text(text)
    assert "jane.doe" not in masked
    assert "415" not in masked
    assert hits == 2


def test_output_sweep_leaves_clean_text_alone():
    text = "Revenue was $187,539.19 across 1,234 orders (avg 158.9724)."
    masked, hits = mask_text(text)
    assert masked == text
    assert hits == 0
