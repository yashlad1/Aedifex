"""Count the corpus, and export it as a transferable bundle.

The bundle is what the operator sends back, so it has to be enough to reconstruct the acquisition
faithfully somewhere else: the bytes, the provenance that says where each one came from, and a
manifest that lets the receiver prove nothing changed in transit.

Two properties are load-bearing.

**Digests are the identity.** Every object is re-hashed as it is written into the bundle and checked
against the digest recorded in ``documents``. A mismatch aborts the export rather than shipping a
file whose provenance no longer describes it -- a corrupt object that arrives labelled as evidence
is worse than no bundle at all.

**Nothing is exported that the database does not know about.** The bundle is built by walking
``documents``, not by listing the bucket, so an object with no provenance row cannot silently ride
along.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from aedifex import __version__
from aedifex.config import get_settings
from aedifex.infrastructure.database.models import (
    CrawlJob,
    Document,
    DocumentRetrieval,
    DocumentUpload,
)
from aedifex.infrastructure.database.session import build_engine
from aedifex.infrastructure.storage.client import build_s3_client
from aedifex.infrastructure.storage.objects import RawObjectStore

BUNDLE_FORMAT: Final[int] = 1
_HASH_CHUNK: Final[int] = 1024 * 1024


class ExportError(Exception):
    """Something that must stop the export. The message is written for an operator's log."""


def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=build_engine(get_settings()), expire_on_commit=False)


def ping() -> str:
    """Prove the configured database is actually reachable, and say which server answered.

    Without this the runner reported a refused connection as "the update did not finish", which
    sends an operator round a loop that cannot succeed. The common cause is another PostgreSQL
    already listening on port 5432, so the host connects to the wrong server rather than to none.
    """
    with _session_factory()() as session:
        version = session.execute(text("SHOW server_version")).scalar_one()
    return str(version)


def count_documents() -> int:
    with _session_factory()() as session:
        return len(session.execute(select(Document.id)).scalars().all())


def _json_safe(value: Any) -> Any:
    """Datetimes and UUIDs to strings; everything else is already JSON-representable."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _rows(session: Session, model: type[Any]) -> list[dict[str, Any]]:
    columns = [column.name for column in model.__table__.columns]
    return [
        {name: _json_safe(getattr(row, name)) for name in columns}
        for row in session.execute(select(model)).scalars().all()
    ]


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str | None:
    """The commit this ran from, when there is a checkout. A downloaded ZIP has no .git."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - absolute path from which(), fixed arguments
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (result.stdout.strip() or None) if result.returncode == 0 else None


def export(destination: Path) -> dict[str, Any]:
    """Write the bundle into ``destination``. Returns the manifest that was written."""
    settings = get_settings()
    store = RawObjectStore(build_s3_client(settings), bucket=settings.storage_bucket)

    # Objects go in at their storage key unchanged, so the bundle mirrors the object store's own
    # layout: `raw/<source>/<aa>/<bb>/<digest><ext>`. Nesting them under a second directory produced
    # `raw/raw/...`, which reads like a mistake and breaks the correspondence a receiver relies on.
    objects_root = destination
    provenance_root = destination / "provenance"
    provenance_root.mkdir(parents=True, exist_ok=True)

    with _session_factory()() as session:
        documents = session.execute(select(Document)).scalars().all()
        objects = [_export_object(store, document, objects_root) for document in documents]
        for name, model in (
            ("documents", Document),
            ("document_retrievals", DocumentRetrieval),
            ("document_uploads", DocumentUpload),
            ("crawl_jobs", CrawlJob),
        ):
            (provenance_root / f"{name}.json").write_text(
                json.dumps(_rows(session, model), indent=2, sort_keys=True)
            )
        # Both origins. A crawl writes a retrieval and an upload writes an upload row; the bundle
        # should describe what it holds either way rather than assuming how it was acquired.
        source_ids = sorted(
            set(session.execute(select(DocumentRetrieval.source_id)).scalars().all())
            | set(session.execute(select(DocumentUpload.source_id)).scalars().all())
        )

    manifest: dict[str, Any] = {
        "bundle_format": BUNDLE_FORMAT,
        "created_at": datetime.now(UTC).isoformat(),
        "software_version": __version__,
        "git_commit": _git_commit(),
        "storage_bucket": settings.storage_bucket,
        "storage_endpoint": settings.storage_endpoint_url,
        "source_ids": source_ids,
        "document_count": len(objects),
        "total_bytes": sum(int(entry["size_bytes"]) for entry in objects),
        "objects": objects,
        "note": (
            "sha256 is the identity of each artifact. Every file under raw/ was re-hashed as it "
            "was written and matched the digest recorded in the documents table."
        ),
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def _export_object(store: RawObjectStore, document: Document, root: Path) -> dict[str, Any]:
    target = root / document.storage_key
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        store.download_to(document.storage_key, target)
    except Exception as error:
        raise ExportError(
            f"could not read stored object {document.storage_key} for document {document.id}: "
            f"{type(error).__name__}: {error}"
        ) from error

    written = _sha256_of(target)
    if written != document.sha256:
        raise ExportError(
            f"stored object {document.storage_key} hashed to {written}, but document "
            f"{document.id} records {document.sha256}. The export was stopped: an artifact whose "
            f"digest does not match its provenance must not be shipped as evidence."
        )
    return {
        "document_id": str(document.id),
        "sha256": document.sha256,
        "size_bytes": int(document.size_bytes),
        "storage_key": document.storage_key,
        "file_format": str(document.file_format),
        "media_type": document.media_type,
        "original_filename": document.original_filename,
        "state": str(document.state),
        "first_seen_at": _json_safe(document.first_seen_at),
    }


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        print("usage: bundle.py [ping | count | export <directory>]", file=sys.stderr)
        return 2
    try:
        if arguments[0] == "ping":
            print(ping())
            return 0
        if arguments[0] == "count":
            print(count_documents())
            return 0
        if arguments[0] == "export" and len(arguments) == 2:
            manifest = export(Path(arguments[1]))
            print(f"{manifest['document_count']} {manifest['total_bytes']}")
            return 0
    except ExportError as error:
        print(str(error), file=sys.stderr)
        return 4
    print("usage: bundle.py [ping | count | export <directory>]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
