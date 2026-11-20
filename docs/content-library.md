# Content creation and library

Open `/create` for rich-text documents, quizzes, assessments, built-in templates, and reusable shared templates. Upload existing packages and files at `/contribute`. `/library` provides search, filters, saved searches, previews, editing, duplication, archive/unarchive, soft deletion/restoration, and bulk lifecycle operations. Create and Upload have separate navigation entries; Content Library is listed once.

## Authoring

The document editor supports visual formatting and HTML source. HTML is sanitized in the browser and again on the server. Quizzes and assessments support single-choice and true/false questions, weighted points, explanations, and a passing threshold. Drafts autosave after a 1.5-second pause and retain a user-scoped browser backup of unsent changes. Optimistic revisions reject stale saves. Incomplete questions may be saved as drafts; submission validates the finished content. Reviewed or published content must be duplicated before editing.

Published assessments accept learner answers through the server, which calculates the weighted score, stores the attempt, and returns the result. Answer keys remain restricted to authorized editors. Learners can review their own recent attempt history.

## Search and lifecycle

Advanced filters cover title, description, tags, subject, language, author, workflow status, department, difficulty, learning standard, duration, content type, file version, and creation/update dates. Searches can be saved with their filters and sort order. Authored bodies and extracted file text participate in search. OpenSearch indexes published accessible content; the library also searches private drafts through the database. For older uploads, run `python scripts/reindex.py --extract-content` from the backend directory to rebuild extracted text and queue OpenSearch updates; run the Celery worker/beat to drain the indexing jobs.

File edits use the same validation and malware-scanning pipeline as upload, append an immutable file version, and preserve the original when replacement fails. Metadata/body snapshots support version history and restoration. Permissions and object ACLs apply to creation, editing, preview delivery, assessment attempts, and lifecycle operations.

## Preview support and limits

| Content | Preview |
| --- | --- |
| Rich text / HTML | Sanitized authored HTML; uploaded HTML runs in an isolated frame |
| Quiz / assessment | Readable author preview; published learner attempt player |
| PDF | Local PDF.js canvas renderer, pagination, extractable page text |
| DOCX / PPTX | Converted text, sections, and embedded images; exact Office layout and animations are not reproduced |
| MP4 / MP3 | Native browser player with byte-range delivery; codecs must be supported by the browser |
| PNG / JPEG / GIF / WebP / SVG | Image preview |
| SCORM ZIP | Manifest launch and basic SCORM 1.2/2004 runtime API with persisted resume state |
| xAPI / cmi5 ZIP | Package launch and scoped preview statement/state endpoints |
| H5P | Local standalone runtime; the upload must include its declared H5P library dependencies |

Package previews use expiring capability URLs, recheck current permissions on every request, and run without same-origin frame privileges. Resources are served from the archive without filesystem extraction. Runtime state is isolated by user, object, and file version. The preview state limit is 64 KB; the xAPI preview store retains up to 100 statements. These adapters provide repository preview and resume functionality, not a certified SCORM LMS, complete SCORM sequencing engine, formal LRS, or authoritative course-completion integration. External network dependencies are restricted by the preview content policy.

## Running and validation

Apply backend Alembic migrations before running, including `d598185e0e15_library_delivery_and_previews`. Install backend requirements and frontend npm dependencies. `npm run dev` and `npm run build` copy the installed H5P and PDF.js runtime assets into ignored public directories; do not remove their pre-scripts when deploying.

Run backend tests with `python -m pytest -q -p no:cacheprovider`. Run frontend checks with `npm test`, `npm run typecheck`, and `npm run build`. Automated acceptance tests cover authoring, template creation, draft validation, lifecycle permissions, filters, answer privacy and scoring, file replacement/history, preview delivery, byte ranges, expired/revoked tickets, runtime state, and xAPI statement conflicts. Browser visual and codec verification remains a separate deployment check.
