# The India Acquisition Runner

A way to run Aedifex's existing acquisition pipeline on a Mac in India, operated by somebody who
cannot use Terminal.

It adds **no capability**. Every byte it collects is collected by the same crawler, through the same
SSRF guard, under the same rate limits, into the same immutable content-addressed store, with the
same provenance rows, from the same approved sources, as a run started by hand in New York. This is
orchestration around the pipeline, not a second pipeline.

---

## 1. Why it exists

Some Indian construction portals — state PWD sites, several RERA portals, all of Odisha — do not
answer from the United States. The connection times out before TLS is negotiated, while
`nhai.gov.in` and `cpwd.gov.in`, both on the central-government network range, answer normally. That
is recorded as **SCRUM-11**, and the conclusion there was to **build nothing**: no proxy, no VPN, no
tunnelling code inside the application. Fetch from a machine that is already in India.

A second Mac exists in India. It is operated by family members who do not use Terminal, and remote
control is unavailable because macOS Accessibility permissions are broken on it. So the pipeline has
to run without anybody technical present.

### What it can reach today, stated plainly

**Nothing that the United States cannot already reach.** Of the eight approved and enabled sources,
seven are manual-upload sources with no URL to crawl, and the eighth is `nhai`, which answers fine
from anywhere. None of the geo-blocked portals is in the registry at all, and `cpwd` — which is not
geo-blocked either — is registered but unverified and disabled.

So the first India run proves the machine, the pipeline and the packaging, and collects nothing new.
The run that justifies the trip is the one after a state PWD or RERA portal has been through the
approval process in [DATA_SOURCES.md](../DATA_SOURCES.md). That is an owner decision and a review,
not an engineering task, and this runner deliberately cannot substitute for it.

---

## 2. What the operator does

1. Download the ZIP.
2. Double-click **`Run Aedifex.command`**.
3. Wait.
4. Send back the file that appears on the Desktop.

There is nothing else. No Terminal, no Docker commands, no Python, no editing files, no choosing
sources, no migrations.

A finished run looks like this:

```
=================================================
  AEDIFEX INDIA ACQUISITION
=================================================

Checking this computer...
  ✓ macOS 14.6
  ✓ Apple Silicon Mac
  ✓ Python 3.13
  ✓ Disk space: 134 GB free
  ✓ Folders are writable
  ✓ Internet connection works
  ✓ Docker is installed

Preparing the software...
  ✓ Software environment is ready
  ✓ Dependencies are up to date

Checking the list of websites to collect from...
  ✓ 1 website(s) approved and ready

Setting up configuration...
  ✓ Configuration ready

Starting the database...
  ✓ Docker is running
  ✓ Database and file storage started
  ✓ Database is ready

Preparing the database...
  ✓ Database is already up to date

Collecting documents...
  Collecting from nhai...
  still working... (1 min)
  ✓ nhai: 17 new document(s)

Preparing the file to send...
  ✓ Result file created

=================================================
  SUCCESS

  17 new document(s) collected.
  17 document(s) in total.

  File to send:
    /Users/family/Desktop/Aedifex-India-2026-08-25.tar.gz
    (24M)

  Please send that file to Yash.
  It is on the Desktop. Attaching it to an email or a message is enough.
=================================================
```

No tracebacks, no Docker logs, no pip output. All of that goes to the run log.

---

## 3. Architecture

```
Run Aedifex.command                 double-clickable launcher; finds the folder, hands over
  └── scripts/india/run.sh          the orchestrator: stage order, and what a finished run says
        ├── lib/logging.sh          console lines, the run log, and the one way a run fails
        ├── lib/preflight.sh        1  can this Mac do the job          (read-only)
        ├── lib/python.sh           2  virtual environment              (make install)
        │   scripts/india/manifest.py  3  the run list, checked against the real registry
        ├── lib/environment.sh      4  .env if absent; manifest values into the environment
        ├── lib/stack.sh            5  PostgreSQL + MinIO               (make up)
        ├── lib/database.sh         6  migrations                       (alembic upgrade head)
        ├── lib/acquire.sh          7  the crawl    (python -m apps.crawler.main crawl <id>)
        └── lib/package.sh          8  the archive
            scripts/india/bundle.py    the export: objects, provenance, manifest
```

Every stage calls something that already existed. The runner has no downloader, no validator, no
storage code, no parser and no rules of its own, and it never opens a socket to a portal.

### The one rule that shapes all of it

**The runner can refuse, and cannot permit.**

`config/india_runner.yaml` names which approved sources to run. It is not a registry and it cannot
approve anything. Every source it names is looked up in `config/sources/` and must be both
`enabled: true` and `verification_status: approved`; anything else stops the run before Docker
starts. That check is the *second* refusal, not the only one — `CrawlRunner` raises
`SourceNotCollectableError` for the same case and modifies nothing before it does. Checking early
exists so the operator reads one sentence instead of watching a crawl begin and stop.

The manifest also cannot set anything except four limits — `max_documents`, `max_pages`,
`max_seconds`, `batch_size` — because those are the only flags the crawl CLI accepts. A key it does
not recognise is an error, so a run list cannot smuggle in a URL, a rate, a permitted format or a
robots setting. Those live in the reviewed registry.

### Configuration, and why it is split in two

| | |
| --- | --- |
| `.env` | Machine defaults. Written on first run **if absent**, then never touched again. Anything an operator or an earlier run left there is kept exactly |
| `config/india_runner.yaml` | The reviewed run list. Its three settings — User-Agent, bucket, storage endpoint — are exported into the crawl process's **environment**, which outranks `.env` in `Settings` |

So the reviewed manifest wins every run without the runner ever editing, overwriting or
second-guessing a file somebody else owns.

The storage endpoint matters more than it looks. Leaving `AEDIFEX_STORAGE_ENDPOINT_URL` unset does
not mean "no storage" — it means **real AWS S3**, which on the India Mac has no credentials and is
not where this evidence belongs. The bucket is `aedifex-india`, deliberately separate from the
development corpus, so "everything this machine acquired" is an exact set rather than a guess.

### The contact address is a hard limit, not a setting

A crawl of a real portal must offer a contact a site operator can reach. Aedifex enforces this in
`Settings.user_agent_names_a_real_contact()`, and [DATA_SOURCES.md](../DATA_SOURCES.md) lists it
under limits that hold regardless of review outcome.

`config/india_runner.yaml` ships with a **placeholder that the runner refuses**. The owner sets a
real URL and address once and commits it. This is not something the operator can or should do, and
the runner does not invent one: choosing what address to publish to a government portal is a
decision, not a default.

---

## 4. Logs

Every run writes `logs/YYYY-MM-DD_HH-MM-SS.log` containing everything — every command, its full
output, pip resolution, Docker output, crawl detail, tracebacks. The console shows status lines
only.

When a run fails, the message names that file and asks for it. It is the only thing the operator
needs to send.

Logs are not deleted by the runner. They are small, and the one from the run that went wrong is
usually the one somebody wants a week later.

---

## 5. Packaging

On success the runner writes `~/Desktop/Aedifex-India-YYYY-MM-DD.tar.gz`, containing:

```
Aedifex-India-2026-08-25/
  manifest.json              bundle format, versions, source ids, and every object's digest
  raw/…                      the artifacts, in the same key layout as the object store
  provenance/
    documents.json           identity, format, size, state
    document_retrievals.json a crawled document: URL, status, headers, timing, verification
    document_uploads.json    an uploaded one: original path, who, when. Both, so the bundle
                             describes what it holds rather than assuming how it arrived
    crawl_jobs.json          the runs themselves, and why each stopped
  logs/…                     this run's log
  india_runner.yaml          the run list this run used
```

Plus `Aedifex-India-YYYY-MM-DD.tar.gz.sha256` beside it, so the receiver can prove the file arrived
intact. Messaging apps have re-encoded attachments before, and a silently truncated bundle otherwise
looks exactly like a successful transfer.

Two properties are load-bearing:

- **Every object is re-hashed as it is written into the bundle** and checked against the digest
  `documents` recorded for it. A mismatch aborts the packaging. An artifact whose digest no longer
  matches its provenance must not be shipped as evidence.
- **The bundle is built by walking `documents`, not by listing the bucket**, so an object with no
  provenance row cannot ride along unnoticed.

Excluded: the virtual environment, the database volume, caches, `node_modules`, and the source tree.
The bundle is evidence and its paperwork.

> **Not yet decided: how a bundle is imported back into the main corpus.** The bytes and the
> provenance are both in the archive, so nothing is lost, but re-ingesting through the upload path
> would record it as an upload rather than the crawl it actually was. That is a real design question
> and it is deliberately not answered here.

---

## 6. Recovery, and running it twice

**Running it again is always safe.** Nothing in the runner deletes a database, removes a volume, or
wipes storage — `docker compose down -v` appears nowhere in it.

Idempotency is inherited rather than implemented:

- Storage is content-addressed, so the same bytes are the same artifact. A re-download is recognised
  as a duplicate rather than stored twice.
- The frontier is persistent, so an interrupted crawl **continues** rather than restarting.
- `alembic upgrade head` applies nothing when the schema is current.
- The dependency install is skipped entirely unless `uv.lock` or `pyproject.toml` changed, recorded
  by a fingerprint in `.venv/.india-runner-install-stamp`.

If a run is interrupted — the lid is closed, the power goes, the window is closed — the next run
picks up from the frontier. Documents already acquired are already safe; they are immutable and were
committed as they arrived, not at the end.

A second run that finds nothing new reports `nothing new (everything already collected)` as a
**warning, not an error**. Reporting it as a failure would teach the operator to ignore failures.

---

## 7. Troubleshooting

The operator is not expected to do any of this. It is here for whoever they call.

| What the run says | What it means |
| --- | --- |
| `Python 3.12 or 3.13 is not installed` | Install Python 3.13 from python.org. macOS's own `python3` may be older or absent |
| `Docker Desktop is not installed` | Install Docker Desktop, then **open it once** so it finishes setting itself up |
| `Docker did not finish starting` | Open Docker Desktop by hand, wait for the whale to stop animating, run again |
| `This Mac cannot reach the internet` | Wi-Fi, or the portal is down. Both are worth retrying later |
| `only N GB of free disk space` | Needs 12 GB for the database, downloads and the archive |
| `the `user_agent` … still carries the placeholder` | **Owner action.** Set a real contact in `config/india_runner.yaml` and commit |
| `may not be collected from` | **Owner action.** The run list names a source that has not been approved. Approve it in `config/sources/` or remove it from the run list |
| `cannot write to …` | The folder was opened from inside the ZIP or a disk image. Drag it to the Desktop first |

Exit codes: `10` preflight, `20` Python, `30` run list, `50` Docker, `60` database, `80`
acquisition, `90` packaging, `1` unexpected.

### The double-click limitation, stated honestly

A ZIP downloaded from GitHub's web interface **does not reliably preserve the executable bit**, and
files downloaded from the internet also carry macOS's quarantine flag. Either can stop a
double-click from working, and neither can be fixed from inside the file.

Two things reduce it to at most one obstacle:

- Only `Run Aedifex.command` needs to be executable. It invokes `bash scripts/india/run.sh` rather
  than executing it, so there are not nine files to fix.
- The repository stores the file with mode `755`, so a `git clone` is always correct.

**The supported way to send this to the India Mac** is therefore not GitHub's "Download ZIP" but an
archive made with a tool that preserves permissions:

```bash
cd /path/to/parent
zip -r Aedifex-India.zip Aedifex -x '*.git*' '*.venv*' '*node_modules*'
```

If GitHub's ZIP is used anyway and double-clicking does nothing, the one-time fix is to open
Terminal once and run `chmod +x "Run Aedifex.command"` in the folder. If macOS says the file is from
an unidentified developer, right-click it, choose **Open**, then **Open** again.

---

## 8. Updating

The runner is part of the repository, so it updates with it: send a new archive, the operator
replaces the folder, double-clicks again.

Two things survive a replacement because they are not in the repository — `.env` and the Docker
volumes holding the database and the objects. Documents already acquired stay acquired.

To change what gets collected, edit `config/india_runner.yaml`, commit, and send a new archive. The
operator never chooses a source and never edits a file.

To add a newly approved portal:

1. Review its terms and record the decision in [DATA_SOURCES.md](../DATA_SOURCES.md).
2. Add it to `config/sources/` with `verification_status: approved` and `enabled: true`.
3. Add one entry under `sources:` in `config/india_runner.yaml`.

Step 3 alone does nothing. That is the point.
