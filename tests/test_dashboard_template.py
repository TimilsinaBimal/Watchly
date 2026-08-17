import re
from pathlib import Path


TEMPLATE = Path(__file__).parents[1] / "app/templates/components/section_dashboard.html"


def test_profile_picker_stays_hidden_until_dashboard_reveals_it():
    html = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r'<div id="dashInstancePicker" class="([^"]+)"', html)

    assert match is not None
    classes = set(match.group(1).split())
    assert "hidden" in classes
    assert not classes.intersection({"sm:flex", "md:flex", "lg:flex", "xl:flex", "2xl:flex"})
