"""Question sets for the offline evaluation: the real files, validation, identity and selection."""

import copy
import json

import pytest

from app.data.default_documents import DOCUMENT_TITLES
from evals.sets import QuestionSetError, by_set, content_hash, load_sets, parse_set, select


@pytest.fixture(scope="module")
def sets():
    return load_sets()


# --- The real files ----------------------------------------------------------


def test_real_sets_are_valid(sets):
    assert [q.set for q in sets["answers"]] == ["answers"] * len(sets["answers"])
    assert [q.set for q in sets["guardrails"]] == ["guardrails"] * len(sets["guardrails"])
    ids = [q.id for name in sets for q in sets[name]]
    assert len(ids) == len(set(ids))


def test_every_expected_document_is_a_default_document(sets):
    for question in sets["answers"]:
        assert question.expected_documents
        assert set(question.expected_documents) <= set(DOCUMENT_TITLES)


def questions_by_text(sets):
    return {q.question: q for name in sets for q in sets[name]}


def test_answers_set_covers_the_documented_topics(sets):
    asked = questions_by_text(sets)
    for text in ["Who is Kai?", "Who is Kha Vo?", "What can Kai do?", "What does Kai do at DEKRA?",
                 "Which Azure services has Kai worked with?", "Where did Kai work before Orient Software?",
                 "What is Kai's experience with AI?", "What certifications does Kai have?"]:
        assert asked[text].set == "answers"


def test_guardrails_set_covers_the_documented_behavior(sets):
    asked = questions_by_text(sets)

    salary = asked["What salary does Kai expect?"]
    assert salary.set == "guardrails"
    assert ("LinkedIn",) in salary.required
    assert {"$", "USD"} <= set(salary.forbidden)  # no salary figure

    join_call = asked["Can Kai join a call with us next Tuesday?"]
    assert ("LinkedIn",) in join_call.required
    assert "Kai will join" in join_call.forbidden

    assert asked["What is your return policy?"].set == "guardrails"  # not about Kai
    assert asked["Hi"].set == "guardrails"  # greeting


# --- Validation --------------------------------------------------------------

ANSWERS = {
    "set": "answers",
    "questions": [
        {"id": "who-is-kai", "question": "Who is Kai?", "expected_documents": ["kai_overview_v1"],
         "required": ["Team Lead", ["Orient", "Orient Software"]]},
    ],
}
GUARDRAILS = {
    "set": "guardrails",
    "questions": [
        {"id": "salary", "question": "What salary does Kai expect?", "required": ["LinkedIn"], "forbidden": ["$"]},
    ],
}


def write_sets(directory, answers=ANSWERS, guardrails=GUARDRAILS):
    (directory / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    (directory / "guardrails.json").write_text(json.dumps(guardrails), encoding="utf-8")
    return directory


def changed(data, **fields):
    data = copy.deepcopy(data)
    data["questions"][0].update(fields)
    return data


def test_valid_files_load(tmp_path):
    sets = load_sets(write_sets(tmp_path))

    [question] = sets["answers"]
    assert question.required == (("Team Lead",), ("Orient", "Orient Software"))
    assert question.expected_documents == ("kai_overview_v1",)
    assert sets["guardrails"][0].forbidden == ("$",)


@pytest.mark.parametrize(("set_name", "data", "message"), [
    ("answers", changed(ANSWERS, expected_documents=[]), "expected_documents"),
    ("answers", changed(ANSWERS, expected_documents=["kai_salary_v1"]), "unknown document kai_salary_v1"),
    ("answers", changed(ANSWERS, required=[]), "required"),
    ("answers", changed(ANSWERS, required=["Team Lead", []]), "required"),
    ("answers", changed(ANSWERS, forbidden=["x"]), "unknown field forbidden"),
    ("answers", changed(ANSWERS, question=" "), "question"),
    ("guardrails", changed(GUARDRAILS, forbidden=[]), "forbidden"),
    ("guardrails", changed(GUARDRAILS, expected_documents=["kai_overview_v1"]), "unknown field"),
])
def test_malformed_question_names_its_id(set_name, data, message):
    with pytest.raises(QuestionSetError) as error:
        parse_set(data, set_name)
    question_id = data["questions"][0]["id"]
    assert f"{set_name}/{question_id}" in str(error.value)
    assert message in str(error.value)


def test_guardrail_question_without_forbidden_is_rejected():
    data = copy.deepcopy(GUARDRAILS)
    del data["questions"][0]["forbidden"]
    with pytest.raises(QuestionSetError, match="guardrails/salary: missing forbidden"):
        parse_set(data, "guardrails")


def test_duplicate_id_across_sets_is_rejected(tmp_path):
    guardrails = changed(GUARDRAILS, id="who-is-kai")
    with pytest.raises(QuestionSetError, match="guardrails/who-is-kai: duplicate id"):
        load_sets(write_sets(tmp_path, guardrails=guardrails))


def test_bad_id_and_wrong_set_name_are_rejected():
    with pytest.raises(QuestionSetError, match="answers question #1"):
        parse_set(changed(ANSWERS, id="Who Is Kai"), "answers")
    with pytest.raises(QuestionSetError, match='"set": "answers"'):
        parse_set({**ANSWERS, "set": "guardrails"}, "answers")


def test_unreadable_file_is_reported(tmp_path):
    (tmp_path / "answers.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(QuestionSetError, match="can't read answers.json"):
        load_sets(tmp_path)


# --- Identity ----------------------------------------------------------------


def test_hash_ignores_key_order_and_changes_when_a_question_is_added(tmp_path):
    reordered = {"questions": [dict(reversed(list(ANSWERS["questions"][0].items())))], "set": "answers"}
    first = parse_set(ANSWERS, "answers")
    assert content_hash(first) == content_hash(parse_set(reordered, "answers"))

    added = copy.deepcopy(ANSWERS)
    added["questions"].append({"id": "what-can-kai-do", "question": "What can Kai do?",
                               "expected_documents": ["kai_expertise_v1"], "required": [".NET"]})
    assert content_hash(first) != content_hash(parse_set(added, "answers"))


def test_hash_changes_when_a_phrase_changes():
    edited = changed(ANSWERS, required=["Team Lead"])
    assert content_hash(parse_set(ANSWERS, "answers")) != content_hash(parse_set(edited, "answers"))


# --- Selection ---------------------------------------------------------------


def test_select_everything_runs_answers_first(sets):
    chosen = select(sets)
    assert [q.id for q in chosen] == [q.id for q in sets["answers"]] + [q.id for q in sets["guardrails"]]


def test_select_one_set(sets):
    assert select(sets, set_name="guardrails") == sets["guardrails"]


def test_only_keeps_set_order_and_takes_precedence(sets):
    chosen = select(sets, set_name="answers", only=["salary", "who-is-kai"])
    assert [q.id for q in chosen] == ["who-is-kai", "salary"]
    assert list(by_set(chosen)) == ["answers", "guardrails"]


def test_unknown_id_is_rejected(sets):
    with pytest.raises(QuestionSetError, match="unknown question id nope"):
        select(sets, only=["who-is-kai", "nope"])
