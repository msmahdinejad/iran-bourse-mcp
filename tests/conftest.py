from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
os.environ.setdefault("IRAN_BOURSE_CODAL_PAGE_GAP", "0")  # replayed Codal pages need no politeness gap


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture()
def fx():
    return load
