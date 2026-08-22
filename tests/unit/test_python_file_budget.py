from pathlib import Path

from scripts.ci.check_python_file_budget import effective_code_lines, violation


def test_effective_code_lines_ignore_blank_and_comment_only_lines() -> None:
    source = """
# comment
value = 1  # inline comment

# another comment
other = 2
"""

    assert effective_code_lines(source) == 2


def test_docstring_lines_count_as_python_content() -> None:
    source = '''"""first
second
"""
value = 1
'''

    assert effective_code_lines(source) == 4


def test_new_or_compliant_file_cannot_cross_hard_max() -> None:
    path = Path("src/request_engine/example.py")

    assert violation(path, 120, None) is None
    assert violation(path, 121, None) is not None
    assert violation(path, 121, 120) is not None


def test_existing_oversized_file_is_ratcheted_not_rewritten() -> None:
    path = Path("tests/example.py")

    assert violation(path, 140, 140) is None
    assert violation(path, 130, 140) is None
    assert violation(path, 141, 140) is not None
