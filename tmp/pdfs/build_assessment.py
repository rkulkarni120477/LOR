from pathlib import Path
from html import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/pdf/ELOR-Gap-Assessment-and-Recommendations.pdf'
OUT.parent.mkdir(parents=True, exist_ok=True)
# ID, priority, title, finding, recommendation, acceptance, evidence
gaps = [
(1,'P1','LMS integration is unfinished','The LMS adapter raises NotImplementedError. LTI launch and grade passback are not implemented, preventing a complete LMS-to-repository workflow.','Select a target LMS and implement the agreed launch, identity mapping, content selection and grade-return contract. Include retry, reconciliation and integration ownership.','Demonstrate authorized launch and correct grade return in the target LMS, including expired credentials and retry scenarios.','backend/app/integrations/lms.py'),
(2,'P1','SCORM runtime is limited','The player exposes SCORM 1.2 and 2004 APIs but largely persists arbitrary cmi.* values. Complete data-model validation, sequencing, navigation and multi-SCO orchestration are not demonstrated.','Publish an explicit supported-feature matrix. Use a proven runtime or implement required validation, lifecycle, sequencing and navigation behavior. Test representative authoring-tool packages.','A representative package suite passes launch, suspend/resume, score, completion, multi-SCO and error-handling checks for each claimed version.','backend/app/assets/player.js; backend/app/services/player.py'),
(3,'P1','xAPI is not a complete LRS','Main ingestion uses a minimal statement schema. The preview player has a separate limited statement/state store. Full protocol support and conformance evidence are absent.','Prefer integration with a conformant external LRS unless owning an LRS is a product requirement. Define supported xAPI version, authority, retrieval, state, idempotency and retention behavior.','Validate required protocol operations and statement identity rules; retain formal conformance evidence for any LRS claim.','backend/app/api/v1/xapi.py; backend/app/schemas/xapi.py; backend/app/api/v1/player.py'),
(4,'P1','Learning records are fragmented','Package activity, assessment attempts and xAPI statements have separate persistence paths. Completion reporting reads xAPI statements, so these paths do not automatically yield a consistent learner record.','Define a canonical learning-event model with learner, object version, registration, attempt, source and timestamps. Map all delivery modes into it with reliable event publication.','A native quiz, SCORM package and xAPI package produce reconcilable progress, score and completion in one learner record.','backend/app/db/models.py; backend/app/services/player.py; backend/app/services/reports.py'),
(5,'P1','Completion metrics can overcount outcomes','Completion reports count completed statements rather than distinct learner/activity/registration outcomes. Different statement IDs can represent repeated reports of the same outcome.','Separate raw event volume from learning outcomes. Agree deduplication and latest/best attempt rules, completion versus success, version changes and recertification periods.','Repeated completion events do not inflate outcome counts; distinct legitimate attempts remain traceable and reconcile to source records.','backend/app/services/reports.py'),
(6,'P1','Background automation is incompletely wired','Report schedules, SLA processing, email and webhooks have service/API implementations, but Celery beat schedules only search indexing.','Wire periodic execution for each required job. Add idempotency, overlap protection, bounded retry/backoff, failure queues and operational alerts.','Due reports, SLA notices and queued deliveries execute without manual API calls; outage/restart tests show no lost or duplicate business actions.','backend/app/worker.py; backend/app/services/report_schedules.py; backend/app/api/v1/notifications.py'),
(7,'P1','HR and vendor adapters remain stubs','HR/SCIM synchronization and vendor ingestion raise NotImplementedError. Organizational updates and catalog refresh are unfinished.','Implement incremental HR/SCIM synchronization with deprovisioning and reconciliation. Add vendor catalog mapping, licensing controls, version updates and failure reporting.','Joiner/mover/leaver changes and vendor updates reconcile correctly; failures are visible and safely replayable.','backend/app/integrations/hr_sync.py; backend/app/integrations/vendor.py'),
(8,'P1','Accessibility assurance is insufficient','The quality agent checks alt-text presence, caption-file presence and license presence. These checks do not establish accessible UI, content or assessments.','Adopt WCAG 2.2 AA as a proposed acceptance target. Combine automated checks with keyboard and screen-reader evaluation; verify caption quality, focus, contrast and assessment alternatives.','Documented automated and human evaluation covers critical journeys, with blocking defects resolved and content exceptions governed.','backend/app/agents/nodes/quality_compliance.py; frontend/tests/'),
(9,'P1','Production malware protection needs validation','ClamAV and quarantine controls exist. The default scanner performs limited signature and executable checks rather than comprehensive malware detection.','Configure the external scanner for production, update signatures, monitor availability and scan latency, and establish quarantine investigation and safe rescan/release procedures.','Malicious fixtures and scanner outages cannot release content; signature freshness, recovery and authorized release are verified.','backend/app/services/malware.py; backend/app/core/config.py'),
(10,'P1','Enterprise SSO needs real-provider acceptance','OIDC authorization code with PKCE and server-side sessions exists. Real-provider evidence for account disablement, changed roles, session revocation and organizational policy enforcement was not reviewed.','Run an enterprise identity acceptance suite. Agree session freshness/revocation behavior, role synchronization and provider logout requirements; remove development login from production operation.','The configured provider passes allowed/denied organization, role-change, disabled-user, session-expiry and logout scenarios under agreed policies.','backend/app/api/v1/auth.py; backend/app/core/security.py; frontend/views/Login.tsx'),
(11,'P1','Production delivery and recovery are not demonstrated','Compose files and AWS guidance exist, but deployment IaC and a CI pipeline were not found. Recovery, rollback and high availability are not evidenced.','Create versioned infrastructure and delivery pipelines with managed secrets and migration gates. Agree RPO/RTO, backups, restoration, rollback and service availability targets.','A staging deployment and rollback succeed; a documented restore drill meets agreed RPO/RTO and verifies content plus database consistency.','infra/docker-compose.yml; infra/docker-compose.stack.yml; infra/aws/README.md'),
(12,'P1','Operational monitoring is incomplete','Logging and readiness checks exist, but readiness covers selected dependencies. Worker, scanner, failed delivery and queue-age monitoring are not demonstrated.','Define service-level objectives, structured correlation IDs, metrics and traces. Monitor dependency health, job age, failures, scanner status and learning-event delivery.','Injected dependency and worker failures generate actionable alerts with tested runbooks; dashboards expose availability and backlog.','backend/app/main.py; backend/app/services/infrastructure.py; backend/app/worker.py'),
(13,'P1','End-to-end quality evidence is limited','Backend and component tests exist. Browser acceptance, accessibility, package compatibility and concurrency evidence was not found in the reviewed inventory.','Add critical browser journeys and permission/failure scenarios. Run representative standards packages, accessibility evaluation and load tests against production-like infrastructure.','Contributor-to-learner journeys pass in CI; package and load evidence meets explicit acceptance thresholds.','backend/tests/; frontend/tests/'),
(14,'P2','Content portability loses information','Bundle import supports file packages only. Rich-text and quiz bundles are refused. Exported metadata is read but not fully applied by the ingest call.','Define a versioned round-trip bundle contract for every content kind. Preserve metadata, authored body, taxonomy mapping and provenance; explicitly define ownership and workflow-state handling.','Export/import round trips preserve supported content and metadata; unsupported fields produce explicit, reviewable diagnostics.','backend/app/services/interop.py'),
(15,'P2','Version comparison omits authored content','Snapshots contain body and kind, but comparison checks selected top-level fields and LOM metadata. Article or quiz changes can be absent from the diff and appear unchanged.','Include body and kind in comparison; provide readable text/question diffs and identify scoring or answer-key changes. Distinguish binary changes from metadata changes.','Article edits, question/options/answer changes and content-kind changes always appear in comparisons and set unchanged to false.','backend/app/services/versioning.py'),
(16,'P2','Assessment capability is basic','Native assessments support single-choice and true/false with weighted scoring. Banks, randomized selection, attempt limits, timing and moderation are not evident.','Define the assessment use cases before extending the engine. Add prioritized question types, banks, attempt and timing policies, feedback rules and moderation controls.','Required policies are enforced server-side, scoring is reproducible, and learner feedback follows the configured release policy.','backend/app/schemas/library.py; backend/app/api/v1/library.py'),
(17,'P2','Content lifecycle governance is incomplete','Approvals, archiving and snapshot retention exist. Periodic review, content expiry, license-expiry enforcement and reuse dependency notifications are not evident.','Add accountable owners, review/expiry dates and automated reminders. Define stale-content withdrawal, license validation and change notifications for downstream reuse.','Expired or overdue items follow agreed visibility rules; owners and affected consumers receive actionable notifications.','backend/app/services/workflow.py; backend/app/services/versioning.py; backend/app/db/models.py'),
(18,'P2','Discovery needs stronger relevance','Main search uses keyword matching and alphabetical ordering; semantic retrieval is a separate agent path. Unified relevance and relevance evaluation are missing.','Build a representative query benchmark. Introduce relevance ordering, synonyms and typo handling, then evaluate hybrid retrieval with authorization-aware results and facets.','Measured search quality improves on the agreed benchmark, while unauthorized or withdrawn content never appears in results or counts.','backend/app/services/search.py; backend/app/agents/tools/vector_retriever.py'),
(19,'P2','Localization is mostly metadata-level','Content language fields exist, but localized UI resources, linked translations, translation approval and RTL validation are not demonstrated.','Externalize UI strings; model translation relationships and source-version drift. Add language fallback, localized formats and prioritized RTL/content validation.','Selected locales pass complete journeys; changed source content flags outdated translations and locale fallback behaves predictably.','frontend/views/; backend/app/schemas/library.py'),
(20,'P2','AI quality needs measurable acceptance criteria','AI suggestions are editable and support a rules fallback. Representative evidence for accuracy, grounding, pedagogy and prompt-injection resistance was not reviewed.','Create a versioned evaluation set and human review rubric. Track generation source/model, source evidence, fallback frequency, latency and cost; test malicious content and prevent unintended actions.','Quality and safety thresholds pass on representative content; reviewers can inspect provenance and distinguish rules output from model output.','backend/app/services/ai_authoring.py; backend/app/agents/'),
(21,'P2','Learner-data lifecycle is undefined','Snapshot retention exists, but complete retention, anonymization, deletion and export workflows for learning statements, activity and attempts are not evident.','Inventory personal data and define approved purpose and retention rules. Implement export/deletion/anonymization with dependencies, backup treatment and documented exceptions.','A test learner can be exported and processed under the approved retention/deletion policy without corrupting required aggregate reporting.','backend/app/db/models.py; backend/app/services/versioning.py; backend/app/services/xapi.py'),
(22,'P2','Documentation materially lags implementation','README and planning documents describe implemented authoring, governance and identity features as missing, making readiness and support decisions unreliable.','Reconcile documentation with executable APIs and code. Maintain a capability matrix with implemented, configured, validated and deferred states, plus operational owners and runbooks.','A reviewer can map every claimed capability to its setup, evidence and limitations; stale stub and missing-feature claims are corrected.','README.md; docs/implementation-plan.md; docs/architecture.md'),
(23,'P3','LMS/LXP scope needs a product decision','Enrollment, assigned learning, prerequisite paths, certificates, recertification and manager dashboards are not evident. These are conditional gaps for a repository product.','Decide whether ELOR owns learning delivery or integrates with an LMS/LXP. Assign each capability and system of record explicitly; avoid duplicating learning administration unintentionally.','An approved product boundary and ownership matrix resolves each capability, with integration contracts or a funded implementation backlog.','backend/app/db/models.py; frontend/views/; backend/app/integrations/lms.py'),
]

styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='Cover',fontName='Helvetica-Bold',fontSize=27,leading=32,textColor=colors.HexColor('#102b46'),spaceAfter=18))
styles.add(ParagraphStyle(name='Deck',fontSize=12,leading=18,textColor=colors.HexColor('#42556a'),spaceAfter=14))
styles.add(ParagraphStyle(name='BodyX',fontSize=9.5,leading=14,spaceAfter=8))
styles.add(ParagraphStyle(name='Gap',fontName='Helvetica-Bold',fontSize=13,leading=17,textColor=colors.HexColor('#102b46'),spaceAfter=9))
styles.add(ParagraphStyle(name='SmallX',fontSize=8,leading=11,textColor=colors.HexColor('#526273'),spaceAfter=8,wordWrap='CJK'))
story=[]
def p(text,style='BodyX'): return Paragraph(text,styles[style])
def add(text,style='BodyX'): story.append(p(text,style))
def labeled(label,text): return p('<b>'+label+'</b> '+escape(text))
add('ENTERPRISE LEARNING OBJECT REPOSITORY','SmallX')
add('Gap Assessment<br/>&amp; Recommendations','Cover')
add('E-learning solution architecture review | 23 November 2026','Deck')
add('23 findings | 13 P1 | 9 P2 | 1 scope-dependent P3','Deck')
add('<b>Assessment:</b> ELOR has a substantial repository foundation. Enterprise learning interoperability, reliable outcome reporting and operational readiness require further implementation and validation.')
add('Existing strengths','Heading2')
add('The reviewed implementation includes authoring, collections, permissions, configurable approval workflows, metadata snapshots, package previews, native assessments, analytics, malware-scanner integration, OIDC/PKCE sign-in and editable AI suggestions. These are recognized capabilities, not missing-feature claims.')
add('Scope and limitations','Heading2')
add('This assessment consolidates the architecture and source review shared in the conversation. It is not a browser acceptance test, load test, penetration test or standards certification. No new acceptance test results are asserted. Findings marked as not demonstrated or not evident identify evidence gaps in the reviewed files, rather than proof that a capability cannot exist elsewhere.')
add('Priority definitions','Heading2')
add('<b>P1:</b> Address before enterprise rollout, or explicitly resolve through the approved product boundary. <b>P2:</b> Address for broader adoption and sustainable governance. <b>P3:</b> Scope decision; not inherently required for a Learning Object Repository.')
add('Reading guide','Heading2')
add('Pages 2-9 contain the complete gap register, with recommendations, acceptance evidence and repository references. Page 10 provides a proposed delivery sequence and standards references. Recommended owners and sequence are proposals, not committed staffing or dates.')
story.append(PageBreak())
for start in range(0,len(gaps),3):
    add('Detailed gap register','Heading1')
    add('FINDINGS %02d-%02d  /  23'%(start+1,min(start+3,23)),'SmallX')
    for n,priority,title,finding,rec,accept,evidence in gaps[start:start+3]:
        block=[p(f'{n:02d}  |  {priority}  |  {escape(title)}','Gap'),labeled('Finding / impact.',finding),labeled('Recommendation.',rec),labeled('Acceptance evidence.',accept),p('<b>Repository evidence:</b> '+escape(evidence),'SmallX'),Spacer(1,10)]
        story.append(KeepTogether(block))
    story.append(PageBreak())
add('Recommended delivery sequence','Heading1')
add('Phase 1 - Agree boundaries and repair correctness','Heading2')
add('<b>Proposed owners:</b> Product owner, learning architect, backend lead. Resolve gap 23 first. Define canonical learning outcomes and completion rules (4-5), select LMS/LRS contracts (1-3), repair authored-content comparison (15), and reconcile capability documentation (22).')
add('Phase 2 - Complete enterprise workflows','Heading2')
add('<b>Proposed owners:</b> Integration, identity and platform leads. Complete LMS/LRS and HR/vendor integrations as required (1-3, 7), operationalize recurring jobs (6), validate SSO and scanning (9-10), and implement learner-data lifecycle controls (21).')
add('Phase 3 - Establish the release gate','Heading2')
add('<b>Proposed owners:</b> QA, accessibility specialist, platform/SRE and security leads. Demonstrate accessible journeys (8), automated delivery and recovery (11), dependency and job monitoring (12), and browser, package and concurrency acceptance (13).')
add('Phase 4 - Expand repository value','Heading2')
add('<b>Proposed owners:</b> Content operations, product and learning design leads. Improve portability (14), assessments (16), content lifecycle (17), discovery (18), localization (19) and measured AI quality (20). Prioritize using user research and adoption data.')
add('Enterprise release decision','Heading2')
add('Require evidence for one agreed LMS-to-learner journey, consistent progress/score/completion across supported delivery modes, unattended job execution, accessible critical journeys, identity enforcement, safe content delivery and a successful restore drill. Every remaining P1 needs a named owner and an explicit release decision. Set thresholds and dates after confirming scope, capacity and target service levels.')
add('Standards and evidence references','Heading2')
add('W3C WCAG 2.2: proposed accessibility baseline, not a certification claim.<br/><link href="https://www.w3.org/TR/WCAG22/" color="#12658b">https://www.w3.org/TR/WCAG22/</link>','SmallX')
add('ADL xAPI LRS certification testing guidance: reference for protocol conformance evidence.<br/><link href="https://www.adlnet.gov/assets/uploads/xAPI%20LRS%20Certification%20Program%20Recommendation.pdf" color="#12658b">ADL - xAPI LRS Certification Program Recommendation</link>','SmallX')
add('Repository references in the gap register are relative to the reviewed LOR checkout. Code was treated as stronger evidence than stale README/planning claims. No deployed production infrastructure or external-provider certification was verified.','SmallX')

def footer(c,doc):
    w,h=A4
    c.setStrokeColor(colors.HexColor('#d7e0e8')); c.line(42,40,w-42,40)
    c.setFont('Helvetica',8); c.setFillColor(colors.HexColor('#526273'))
    c.drawString(42,27,'ELOR | Architecture assessment | 23 November 2026')
    c.drawRightString(w-42,27,str(doc.page))
doc=SimpleDocTemplate(str(OUT),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=38,bottomMargin=53,title='ELOR Gap Assessment and Recommendations',author='E-learning Solution Architecture Review')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(OUT)

import fitz
pdf=fitz.open(str(OUT))
print('Pages:',len(pdf))
all_text='\n'.join(page.get_text() for page in pdf)
for n,priority,title,*_ in gaps:
    assert title in all_text, title
assert all_text.count('Acceptance evidence.')==23
render_dir=ROOT/'tmp/pdfs/rendered'; render_dir.mkdir(parents=True,exist_ok=True)
from PIL import Image,ImageOps,ImageDraw
thumbs=[]
for i,page in enumerate(pdf):
    pix=page.get_pixmap(matrix=fitz.Matrix(1.2,1.2))
    target=render_dir/f'page-{i+1:02d}.png'; pix.save(str(target))
    im=Image.open(target).convert('RGB'); im.thumbnail((298,422))
    tile=Image.new('RGB',(318,450),'#dce3e9'); tile.paste(im,((318-im.width)//2,6)); ImageDraw.Draw(tile).text((12,432),f'Page {i+1}',fill='black'); thumbs.append(tile)
sheet=Image.new('RGB',(318*3,450*((len(thumbs)+2)//3)),'white')
for i,im in enumerate(thumbs): sheet.paste(im,((i%3)*318,(i//3)*450))
sheet.save(str(render_dir/'contact-sheet.png'))
print('Content checks passed; rendered all pages.')
