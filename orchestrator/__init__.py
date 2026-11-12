"""Agent orchestrator: a back-end agent, a front-end agent and a reviewer, run by a plain Python loop.

    python -m orchestrator "a to-do list app"

Read the files in this order: __main__.py (wiring), orchestrator.py (the loop and
the routing rules), agents.py (the three agents), llm.py (the model client).
See README.md for the flow.
"""
