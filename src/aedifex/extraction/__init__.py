"""Extraction: turning stored bytes into facts, and knowing when we cannot.

The one thing declared at package level is which formats an extractor actually exists for. It lives
here rather than in ``domain.files`` because it is not a property of the format — a PNG is a
perfectly good file — but of this package's capabilities, and it changes when a reader is added.
"""

from __future__ import annotations

from typing import Final

from aedifex.domain.files import FileFormat

__all__ = ["READABLE_FORMATS"]

READABLE_FORMATS: Final[frozenset[FileFormat]] = frozenset({FileFormat.PDF, FileFormat.XLSX})
"""Formats a reader exists for today.

Storage deliberately accepts more. A JSON API response is good evidence — the Consumer Price Index
arrives no other way — and acquiring an artifact is a separate capability from being able to read
one. Conflating the two produced a nonsense error once: a stored ``.json`` reached the PDF reader
and came back "stream has ended unexpectedly", which sends an operator hunting for a corrupt
download that does not exist. Anything outside this set is stored, provenanced, listed, and
reported as ``unsupported`` by name.

Two formats, and the order they were added in is the wrong way round for the product: the
spreadsheet reader matters more than the PDF one, because a spreadsheet already carries the rows,
columns and cell positions a rule needs (SRS principle 14).
"""
