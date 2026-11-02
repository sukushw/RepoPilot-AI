from __future__ import annotations

from app.modules.crashfix.parser import format_parsed_summary, parse_android_crash

SAMPLE = """\
FATAL EXCEPTION: main
Process: com.example.app, PID: 1234
java.lang.IllegalStateException: Fragment HomeFragment not attached to a context.
    at androidx.fragment.app.Fragment.requireContext(Fragment.java:1000)
    at com.example.app.ui.HomeFragment.onResume(HomeFragment.kt:42)
    at android.app.Activity.performResume(Activity.java:100)
"""


def test_parse_identifies_app_frame():
    parsed = parse_android_crash(SAMPLE)
    assert parsed.exception_type == "java.lang.IllegalStateException"
    assert parsed.target_frame is not None
    assert parsed.target_frame.file_name == "HomeFragment.kt"
    assert parsed.target_frame.line_number == 42
    assert parsed.target_frame.is_framework is False


def test_framework_frames_flagged():
    parsed = parse_android_crash(SAMPLE)
    frameworks = [f for f in parsed.all_frames if f.is_framework]
    assert any("androidx" in f.class_name for f in frameworks)


def test_empty_log():
    parsed = parse_android_crash("just a normal chat message, nothing here")
    assert parsed.is_empty or parsed.target_frame is None


def test_summary_mentions_exception():
    summary = format_parsed_summary(parse_android_crash(SAMPLE))
    assert "IllegalStateException" in summary
