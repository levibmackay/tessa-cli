"""Connectors: pure functions that fetch data from external personal-assistant
sources (stock indices, AI news, Canvas, Gmail, Outlook).

Same purity contract as `tools/`: no UI, no LLM, no confirmation prompts —
just plain functions that take plain arguments and return plain data, or
raise `ConnectorError` with a message suitable for showing to the model.
"""

from __future__ import annotations


class ConnectorError(Exception):
    """A connector could not fetch data; message is shown to the model."""
