from app.scraper import _sanitize_company_name


def test_sanitize_company_name_rejects_block_page_titles() -> None:
    assert _sanitize_company_name("Access Denied", "www.lakera.ai") == "Lakera"
    assert _sanitize_company_name("Just a moment...", "sentra.io") == "Sentra"


def test_sanitize_company_name_keeps_valid_company_names() -> None:
    assert _sanitize_company_name("Lakera", "www.lakera.ai") == "Lakera"
    assert _sanitize_company_name("Concentric AI", "concentric.ai") == "Concentric AI"


def test_sanitize_company_name_rejects_marketing_titles() -> None:
    assert _sanitize_company_name("BigID: Enterprise Data Security Platform for DSPM & AI", "bigid.com") == "Bigid"
    assert _sanitize_company_name("Cyber Security Leader | Imperva, Inc.", "www.imperva.com") == "Imperva"
    assert _sanitize_company_name("Home Redesign", "sentra.io") == "Sentra"
