"""Tool-result capping: every shape a tool can return gets bounded.

The cap exists because every agent step re-prefills the whole message
history — one verbose tool result otherwise taxes every later model call.
Strings were capped from the start (``cap_text``); structured results used
to bypass it entirely.
"""

from agent_core.runtime.text import cap_result, cap_text


class TestCapText:
    def test_short_string_passes_through(self) -> None:
        assert cap_text("short", max_chars=10) == "short"

    def test_long_string_keeps_head_and_tail(self) -> None:
        value = "H" * 5000 + "MIDDLE" + "T" * 5000
        capped = cap_text(value, max_chars=1000, keep_head=500)
        assert capped.startswith("H" * 500)
        assert capped.endswith("T" * 500)
        assert "truncated" in capped
        assert "MIDDLE" not in capped
        assert len(capped) < 1200


class TestCapResult:
    def test_scalar_passthrough(self) -> None:
        assert cap_result(42) == 42
        assert cap_result(None) is None
        assert cap_result(True) is True

    def test_short_dict_untouched(self) -> None:
        result = {"rows": [1, 2, 3]}
        assert cap_result(result) == result

    def test_huge_dict_is_capped_to_a_string(self) -> None:
        result = {"rows": ["x" * 100] * 200}  # ~20 KB rendered
        capped = cap_result(result)  # default budget: 4000/2000
        assert isinstance(capped, str)
        assert len(capped) < 4200
        assert "truncated" in capped

    def test_huge_list_is_capped_to_a_string(self) -> None:
        result = [{"name": f"item-{i}", "blob": "y" * 100} for i in range(100)]
        capped = cap_result(result, max_chars=2000)
        assert isinstance(capped, str)
        assert len(capped) < 2200
