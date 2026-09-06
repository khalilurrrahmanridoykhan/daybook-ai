import pytest

from app.services.tools import ToolError, calculate, call_tool, current_datetime


def test_calculate_basic_arithmetic():
    assert calculate("2 + 3 * 4")["result"] == 14


def test_calculate_supports_parentheses_and_power():
    assert calculate("(2 + 1) ** 2")["result"] == 9


def test_calculate_rejects_function_calls():
    with pytest.raises(ToolError):
        calculate("__import__('os').system('echo hi')")


def test_calculate_rejects_attribute_access():
    with pytest.raises(ToolError):
        calculate("os.system('ls')")


def test_calculate_division_by_zero_raises_tool_error():
    with pytest.raises(ToolError):
        calculate("1 / 0")


def test_current_datetime_is_utc_iso():
    result = current_datetime()
    assert result["utc"] is True
    assert "T" in result["iso"]


def test_call_tool_dispatches_by_name():
    result = call_tool("calculate", {"expression": "10 / 2"})
    assert result["result"] == 5.0


def test_call_tool_unknown_name_raises():
    with pytest.raises(ToolError, match="Unknown tool"):
        call_tool("not_a_real_tool", {})
