"""The CLI chatbot invites questions about Kai (spec profile-assistant).

chatbot.py is read as source, not imported: importing it needs `requests`, which
the app doesn't depend on, and it runs `pip install rich` when rich is missing.
"""

import ast
import pathlib

CHATBOT = pathlib.Path(__file__).resolve().parents[1] / "chatbot.py"


def constant(name: str):
    """The value of a module-level constant assigned in chatbot.py."""
    tree = ast.parse(CHATBOT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not defined in chatbot.py")


def test_example_questions_are_about_kai():
    examples = constant("EXAMPLE_QUESTIONS")

    assert "Who is Kai?" in examples
    assert "What can Kai do?" in examples
    for question in examples:
        for wording in ("return", "shipping", "sizing", "polic"):
            assert wording not in question.lower(), question


def test_welcome_text_invites_questions_about_kai():
    assert constant("WELCOME_TEXT") == "Ask about Kai (Kha Vo): experience, skills and work."


def test_no_store_wording_left_in_the_chatbot():
    source = CHATBOT.read_text(encoding="utf-8").lower()

    for wording in ("return policy", "shipping", "sizing", "our policies", "cannot be returned"):
        assert wording not in source, wording
