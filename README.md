# TRACE — Investigation Intelligence (Final Hackathon Prototype)

TRACE converts fragmented complaints and evidence into reviewable investigative leads. It is a local-first Flask + SQLite prototype with a responsive dashboard.

## Quick start

- Python 3.10+
- `pip install -r requirements.txt`
- `python app.py`
- Open `http://127.0.0.1:5000`
- Click **Load interactive demo data** on the empty dashboard.

## 12 core features

1. Case registration — structured victim, incident, category, loss and transaction details.
2. Evidence upload — files/text with SHA-256 hashes and audit timestamps.
3. AI evidence processing — text extraction and NLP-style identifier parsing; image/PDF OCR is an extension point.
4. Entity resolution — phone, UPI, email, transaction ID, URL and account-like identifiers.
5. Fraud network graph — visual cross-case relationship graph.
6. Cross-case link discovery — candidate links from shared identifiers.
7. Transaction flow — transaction references retained for tracing; full fund-flow reconstruction needs structured statement data.
8. Temporal analysis — incident and evidence timestamps retained for chronological analysis.
9. Mule detection — surfaced as an investigative pattern to review; no automated designation of a person as a mule.
10. Explainable risk score — heuristic score with visible reasons, never presented as a probability.
11. AI investigation copilot — grounded Q&A over current workspace counts and evidence status.
12. Auto report generation — JSON export with cases, entities, evidence hashes and relationships.

## Two unique selling points

### 1. Geospatial intelligence & inter-agency coordination
- Optional coordinates, jurisdiction, location source and accuracy radius on case registration.
- Map view plots reported locations and uncertainty circles.
- Human-approved coordination request workflow, beginning with a minimal hit notice and recording approval/acknowledgement/decline.
- This demo logs requests locally; it does not contact police units or transmit sensitive case information.

### 2. False-Link Firewall
- Every relationship is a candidate association, not a presumed criminal connection.
- Investigators can mark links Supported, Unverified Association or Dismissed.
- Review status is retained when the network refreshes.
- Single-identifier matches are flagged for review by default; decisions remain under investigator control.

## Training / setup needed?

**No custom model training is required** to run or demonstrate this version. The current extraction, matching and triage are deterministic, explainable baseline methods. For stronger AI, connect pretrained OCR (e.g. Tesseract), multilingual NLP/NER and a grounded LLM only after obtaining suitable data permissions and testing. Training a custom model is optional and should be considered only after collecting a labelled, representative dataset and defining evaluation metrics.

## Demo walkthrough

1. Load the sample cases from the dashboard.
2. Open a case; upload/paste text containing phone numbers, UPI handles, transaction IDs or URLs.
3. Inspect extracted entities and explainable score reasons.
4. Open Fraud Network; inspect cross-case links and change their review status.
5. Open Geospatial; add coordinates to a case, inspect map markers/accuracy radius, and log a coordination request.
6. Open Reports & Audit; download the JSON export.

## Honest limitations / safety

- Not a production investigative system and not a source of proof or guilt findings.
- Demo records are synthetic. Do not upload real victim data into a public deployment.
- IP/cell-tower geolocation, OCR for scans, bank transaction ingestion, live inter-agency integrations, multilingual entity extraction and real LLM copilot need separate integration, access controls and validation.
- Map tiles require internet access. Without network access, the rest of the app still runs.
- Use HTTPS, authentication, role-based access, encryption at rest, retention policies, consent/legal basis, audit logging and security review before any real-world deployment.
