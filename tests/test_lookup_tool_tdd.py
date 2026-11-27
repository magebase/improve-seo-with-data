"""SMSRiver lookup tools are not arithmetic calculators."""

from verify_product_functionality import (
    verify_lookup_tool_functionality,
    verify_product_functionality,
)


def test_smsriver_text_lookup_tool_passes_without_numeric_calculator_inputs():
    html = """
    <form>
      <input type="text" name="mcc" placeholder="Enter MCC or MNC">
      <button type="submit">Look up</button>
    </form>
    <table><tbody><tr><td>310</td><td>260</td></tr></tbody></table>
    """

    result = verify_product_functionality(
        "https://smsriver.com/tools/mcc-mnc-telecom-lookup/", html
    )

    assert result.product_type == "lookup_tool"
    assert result.passed is True


def test_lookup_tool_fails_without_a_result_surface():
    result = verify_lookup_tool_functionality(
        "https://smsriver.com/tools/mcc-mnc-telecom-lookup/",
        "<input type='text'><button>Look up</button>",
    )

    assert result.passed is False
