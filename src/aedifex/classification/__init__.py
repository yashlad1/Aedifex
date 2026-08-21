"""Proposing what a document is, deterministically, without deciding anything.

This is the classifier stage of the pipeline in SRS §6 — and it is deliberately the weakest thing
that could occupy that slot. It reads the name the uploader gave the file and nothing else.

Why that is the right first classifier rather than a placeholder for a better one: the filenames a
customer actually uploads are *written by a person who knows what the document is*. ``BOQ.xlsx``,
``RA_Bill_17.xlsx``, ``JMR_17.jpg``, ``Architect Certificate.pdf``, ``Completion Certificate.pdf`` —
that is the real target corpus, and a regex over those names beats a model that has to recover the
same information from pixels. Reading the contents to make a *suggestion* would mean opening every
document twice, and the second read would be the expensive one.

Two boundaries this module must not cross, both learned the hard way:

* **A suggestion is never a decision.** Nothing here writes ``documents.document_type``. It produces
  a proposal that lands in ``suggested_document_type``, and only a person moves it across. The type
  gates whether the extractor treats a quoted amount as a fact about this document; five false facts
  came from a role that looked inferable and was not.
* **A suggestion is never an authority.** A classifier may say "this looks like a bill of
  quantities". It may never say "this is reference material rather than project evidence", because a
  model concession agreement and an executed one are the same clauses in the same order.

No model, no LLM, no learned weights. When that changes, ``classifier_version`` is the column that
will say so, and the boundaries above do not move.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from aedifex.domain.documents import DocumentType

__all__ = [
    "CLASSIFIER",
    "CLASSIFIER_VERSION",
    "Suggestion",
    "classifier_identity",
    "suggest_document_type",
]

CLASSIFIER: Final[str] = "filename_keywords"
CLASSIFIER_VERSION: Final[int] = 1


def classifier_identity() -> str:
    """What goes in ``documents.classifier_version``: which classifier, and which version of it.

    Both, in one string, because a future model-based classifier and this one must be
    distinguishable in the row rather than by remembering what was deployed that week.
    """
    return f"{CLASSIFIER}:{CLASSIFIER_VERSION}"


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A proposed document type, what in the name suggested it, and how specific that was."""

    document_type: DocumentType
    confidence: float
    """How *specific* the matched phrase is — not a probability, and not comparable across
    classifiers.

    "bill of quantities" is unambiguous; a bare "boq" is very likely; "contract" appears in the name
    of every document belonging to a contract. The number orders those three and nothing more. It
    must never be summed, averaged, or fed into a rule: no finding may rest on it, because the
    trust boundary says a reading becomes a fact through deterministic validation or a person, never
    through a confidence.
    """

    matched: str
    """The phrase that fired, so a suggestion is explainable without re-running anything."""

    classifier: str = ""

    def __post_init__(self) -> None:
        if not self.classifier:
            object.__setattr__(self, "classifier", classifier_identity())

    def describe(self) -> str:
        return f"{self.document_type.value} (matched {self.matched!r}, {self.confidence:.2f})"


# Ordered, most specific first: the first rule that matches wins, so "bill of quantities" is never
# reached by the looser "boq" rule and "priced bill of quantities" cannot be claimed by "bill".
#
# Every phrase here comes from a filename that exists — either in the acquired corpus (the IIT
# Bombay building set, the NHAI validation set) or in the list of documents a customer said they
# would upload. Nothing is here on the grounds that it might appear one day; an unused rule is a
# rule nobody has checked.
_RULES: Final[tuple[tuple[str, DocumentType, float], ...]] = (
    # --- the spine: quantities, measurement, claim ---------------------------------
    (r"bill of quantit(y|ies)", DocumentType.BILL_OF_QUANTITIES, 0.95),
    (r"\bboq\b", DocumentType.BILL_OF_QUANTITIES, 0.85),
    (r"schedule of (rates|quantities)", DocumentType.SCHEDULE_OF_RATES, 0.9),
    (r"\b(dsr|sor)\b", DocumentType.SCHEDULE_OF_RATES, 0.6),
    (
        r"joint measurement|measurement (sheet|book|record)|\bjmr\b|\bmb\b",
        DocumentType.MEASUREMENT_BOOK,
        0.9,
    ),
    (
        r"running (account )?(bill|acc)|\bra bill\b|\bra\d+\b|interim payment",
        DocumentType.RUNNING_BILL,
        0.9,
    ),
    # --- certification and money ---------------------------------------------------
    (
        r"payment certificate|architect'?s? certificate|\bipc\b",
        DocumentType.PAYMENT_CERTIFICATE,
        0.85,
    ),
    (r"(tax |gst )?invoice", DocumentType.INVOICE, 0.85),
    (r"bank guarantee|\bbg\b", DocumentType.BANK_GUARANTEE, 0.7),
    # --- change ---------------------------------------------------------------------
    (r"variation|change order|deviation statement", DocumentType.CHANGE_ORDER, 0.85),
    (r"(technical )?specification|\bspecs?\b", DocumentType.TECHNICAL_SPECIFICATION, 0.8),
    (r"corrigendum|addendum|amendment", DocumentType.CORRIGENDUM, 0.8),
    # --- material ------------------------------------------------------------------
    (r"purchase order", DocumentType.PURCHASE_ORDER, 0.9),
    (r"goods receipt|\bgrn\b", DocumentType.GOODS_RECEIPT_NOTE, 0.85),
    (r"delivery challan|\bchallan\b", DocumentType.DELIVERY_CHALLAN, 0.8),
    # --- quality -------------------------------------------------------------------
    (
        r"test (certificate|report)|cube test|material test",
        DocumentType.MATERIAL_TEST_CERTIFICATE,
        0.85,
    ),
    (r"inspection (report|record)", DocumentType.INSPECTION_REPORT, 0.85),
    # --- procurement and the commercial basis ---------------------------------------
    (r"notice inviting tender|tender notice|\bnit\b", DocumentType.TENDER_NOTICE, 0.9),
    (
        r"award (letter|notice)|letter of (award|acceptance)|\bloa\b",
        DocumentType.AWARD_NOTICE,
        0.85,
    ),
    (r"financial bid|price bid|bid document", DocumentType.BID_DOCUMENT, 0.8),
    # "conditions of contract" is proposed as CONTRACT and not MODEL_AGREEMENT on purpose. The two
    # are indistinguishable by name — IIT Bombay's GCC is a template and reads exactly like an
    # executed one — and choosing the reference type would be the classifier deciding authority,
    # which is the one thing it may not do. A person resolves it.
    (r"conditions of contract|\bgcc\b|\bscc\b|agreement|contract", DocumentType.CONTRACT, 0.6),
    # --- reference -----------------------------------------------------------------
    (r"audit report|performance audit|\bcag\b", DocumentType.AUDIT_REPORT, 0.85),
    (r"drawing|\bgfc\b|\bdwg\b", DocumentType.DRAWING, 0.8),
)

_COMPILED: Final[tuple[tuple[re.Pattern[str], DocumentType, float], ...]] = tuple(
    (re.compile(pattern), document_type, confidence)
    for pattern, document_type, confidence in _RULES
)

# Word separators in filenames, plus the extension: "iitb-h19-priced-bill-of-quantities.pdf" has to
# read as a sentence before any of the phrases above can match it.
_SEPARATORS: Final[re.Pattern[str]] = re.compile(r"[-_.\s()\[\]]+")


def _normalise(filename: str) -> str:
    """Turn a filename into something the rules can read: lowercase, separators as spaces."""
    return _SEPARATORS.sub(" ", filename.lower()).strip()


def suggest_document_type(filename: str) -> Suggestion | None:
    """Propose a type from the name of a file, or ``None`` when nothing matches.

    ``None`` is the common and correct answer for ``document (1).pdf`` or ``scan0007.pdf``, and it
    must stay distinguishable from a low-confidence guess: no suggestion means the workspace shows
    the declared type unchallenged, whereas a weak suggestion means something disagrees with it.

    Deterministic and side-effect free. Given the same name it returns the same proposal forever,
    which is what makes it safe to re-run over a corpus and compare.
    """
    normalised = _normalise(filename)
    if not normalised:
        return None
    for pattern, document_type, confidence in _COMPILED:
        found = pattern.search(normalised)
        if found is not None:
            return Suggestion(
                document_type=document_type,
                confidence=confidence,
                matched=found.group(0),
            )
    return None
