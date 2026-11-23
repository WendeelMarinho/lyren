import pytest

from lyren_eval.graders import GRADERS, normalize


@pytest.mark.parametrize(
    ("grader", "answer", "expected", "passes"),
    [
        ("exact", "  Canberra. ", "canberra", True),
        ("exact", "Sydney", "Canberra", False),
        ("exact", "Nao", "não", True),
        ("exact_cased", "OK", "OK", True),
        ("exact_cased", "ok", "OK", False),
        ("numeric", "A resposta é 391.", 391, True),
        ("numeric", "1.234,56", "1234.56", True),
        ("numeric", "1.234.567", 1234567, True),
        ("numeric", "2.500", "2.5", True),
        ("numeric", "3.91", 391, False),
        ("numeric", "2,5", "2.5", True),
        ("numeric", "sem numero", 3, False),
        ("contains_all", "s[::-1]", ["[::-1]"], True),
        ("contains_all", "reversed(s)", ["[::-1]"], False),
        ("regex", "05/03/2026", r"^\d{2}/\d{2}/\d{4}$", True),
        ("json_keys", 'texto {"nome": "Ana", "idade": 30} fim', ["nome", "idade"], True),
        ("json_keys", '{"nome": "Ana"}', ["nome", "idade"], False),
        ("json_keys", "nao e json", ["nome"], False),
    ],
)
def test_grader_verdicts(grader, answer, expected, passes):
    assert GRADERS[grader](answer, expected) is passes


def test_normalize_folds_accents_case_and_trailing_punctuation():
    assert normalize("  Não!  ") == "nao"


def test_normalize_can_keep_accents():
    assert normalize("Não", fold_accents=False) == "não"
