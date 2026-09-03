"""
Local tests for KPI suggestions (no Azure / OpenAI required).

Run from TomGeneratorRaja project root:
  python test_kpi_suggestions.py
"""

from main import apply_kpi_suggestions_to_measures, KpiSuggestion

SAMPLE = [
    {"name": "Performance", "expression": "1"},
    {"name": "Production Efficiency", "expression": "2"},
    {
        "name": "OEE",
        "expression": "IF([Performance] = 0, 0, [Performance] * [Quality])",
    },
    {"name": "Quality", "expression": "0.9"},
]


def test_with_suggestions():
    s = KpiSuggestion(
        remap={"Performance": "Production Efficiency"},
        remove=["Performance"],
    )
    out = apply_kpi_suggestions_to_measures(SAMPLE, s)
    names = [m["name"] for m in out]
    assert "Performance" not in names
    assert "Production Efficiency" in names
    oee = next(m for m in out if m["name"] == "OEE")
    assert "[Performance]" not in oee["expression"]
    assert "[Production Efficiency]" in oee["expression"]
    print("PASS: with suggestions")


def test_without_suggestions():
    out = apply_kpi_suggestions_to_measures(SAMPLE, None)
    assert len(out) == len(SAMPLE)
    print("PASS: without suggestions")


if __name__ == "__main__":
    test_with_suggestions()
    test_without_suggestions()
    print("\nAll tests passed.")