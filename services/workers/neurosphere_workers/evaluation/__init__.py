"""PRP-16 evaluation worker: budgeted, stratified sampling over the redacted archive (item 2).

Classification and judge approval are checked before every judge call; budgets are reserved before
the call, never reconciled after it. ``pipeline.py`` (item 6) wires sandbox output to the store.
"""
