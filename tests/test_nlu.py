from __future__ import annotations

import pytest

from app.services.nlu_service import classify

CRASH = """\
java.lang.NullPointerException: boom
    at com.example.app.HomeFragment.onResume(HomeFragment.kt:42)
"""


@pytest.mark.parametrize(
    "text,expected",
    [
        ("review my latest changes", "review"),
        ("fix the null pointer in HomeFragment", "bugfix"),
        ("refactor the networking layer", "refactor"),
        ("explain how the login flow works", "explain"),
        ("analyze my repository for performance issues", "analyze"),
        ("run the unit tests", "test"),
        ("build the app with gradle", "build"),
        ("implement a dark mode toggle", "generate"),
        ("what is the capital of France", "ask"),
    ],
)
def test_classify_intent(text, expected):
    assert classify(text).name == expected


def test_classify_stacktrace_is_crash():
    assert classify(CRASH).name == "crash"
