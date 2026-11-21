"""
Offline evaluation of the profile assistant's answers.

    python -m evals                      # both question sets
    python -m evals --set guardrails     # one set
    python -m evals --only who-is-kai    # chosen questions
    python -m evals --local              # never send results to Datadog

Asks the questions in evals/questions/*.json through the local RAG pipeline and
scores each answer with deterministic checks; no model grades the answers. With
DD_API_KEY and DD_APP_KEY in .env, each set run is also recorded as a Datadog
experiment. See README.md, "Evaluating answers".

Design: openspec/changes/datadog-rag-evaluation/design.md
"""
