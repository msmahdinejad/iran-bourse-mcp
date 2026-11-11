"""The Persian guide is the "راهنمای کامل" linked from both READMEs.

It is hand-written, so it drifts when tools are added. The 0.4.0 release added
the holiday calendar, options/futures, the fund registry and the commodity and
energy exchanges, but ``docs/GUIDE.fa.md`` still named only 27 of the 40 tools
and said in its limitations section that holidays were not modelled and that
options, the commodity exchange and the energy exchange were not covered.
Both statements were the opposite of what shipped. CI now catches it.
"""

from pathlib import Path

from iran_bourse_mcp.server import mcp

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "GUIDE.fa.md"


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


async def test_every_registered_tool_is_named_in_the_persian_guide():
    """A reader following the README's "full guide" link must see every tool."""
    guide = _guide()
    registered = {tool.name for tool in await mcp.list_tools()}
    missing = sorted(name for name in registered if f"`{name}`" not in guide)
    assert not missing, (
        "docs/GUIDE.fa.md does not name these registered tools: "
        f"{', '.join(missing)}. Add a Persian line for each; see docs/TOOLS.md "
        "for what they return."
    )


def test_the_guide_does_not_deny_features_that_ship():
    """Regression guard for the two sentences that contradicted the 0.4.0 release."""
    guide = _guide()
    stale = (
        "تعطیلات رسمی مدل نشده",
        "آپشن، بورس کالا و انرژی هنوز",
    )
    for phrase in stale:
        assert phrase not in guide, (
            f"docs/GUIDE.fa.md still says {phrase!r}, which is no longer true since 0.4.0."
        )
    # The limitations section must describe the real boundary, not deny the feature.
    assert "تقویم تعطیلات رسمی" in guide
