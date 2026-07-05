# Deployment

## Local prototype run (ngrok)

1. Create Firestore (Native mode) + a service account with Calendar & Firestore access.
   Share the clinic Google Calendar with the service-account email ("Make changes to events").
2. `cp .env.example .env` and fill values. Put the service-account JSON at `./service-account.json`.
3. Create the Python 3.12 env and install (the repo pins Python 3.12 for stdlib `audioop`):
   - With uv (recommended): `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"`
   - Or plain: `python3.12 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"`
4. `.venv/bin/uvicorn app.main:app --port 8080`
5. `ngrok http 8080` → copy the https URL into `PUBLIC_BASE_URL` in `.env`, restart uvicorn.
6. In Twilio Console → your number → Voice webhook: `POST https://<ngrok>/voice`
7. Call the number and book. Verify: Calendar event created, WhatsApp + email received.
8. Reminders: `curl -X POST https://<ngrok>/tasks/reminders` (seed a soon appointment first).

## Cloud Run

- Build & deploy (fill `<REGION>`):
  ```
  gcloud run deploy voice-agent --source . --region <REGION> --allow-unauthenticated \
    --set-env-vars "$(grep -v '^#' .env | grep -v GOOGLE_APPLICATION_CREDENTIALS | xargs | sed 's/ /,/g')"
  ```
  (Dockerfile lives in `deploy/`; if `--source .` doesn't pick it up, move it to repo root or pass `--dockerfile deploy/Dockerfile` with a builder that supports it.)
- Attach the service account to the Cloud Run service (`--service-account`) so Calendar +
  Firestore auth works via ADC. Then remove `GOOGLE_APPLICATION_CREDENTIALS` from env — the
  service uses the attached SA identity, and `build_google_service` should be switched to
  default credentials in that mode (or keep mounting a key via Secret Manager).
- Set `PUBLIC_BASE_URL` to the Cloud Run URL; update the Twilio Voice webhook to it.

## Cloud Scheduler (reminders)

- ```
  gcloud scheduler jobs create http reminders --schedule "*/5 * * * *" \
    --uri "https://<cloud-run-url>/tasks/reminders" --http-method POST \
    --oidc-service-account-email <sa>@<project>.iam.gserviceaccount.com
  ```
- Lock down `/tasks/reminders` to the scheduler SA (require an OIDC token) before real use.

## WhatsApp templates (production)

- Twilio WhatsApp requires approved templates for business-initiated messages outside the
  24h window. For the sandbox/prototype, freeform `body` works after opting a tester in.
  For launch, submit confirmation + reminder templates and switch `app/messaging.py` to
  `content_sid` + `content_variables`.

## Notes / prototype boundaries

- Sessions use `InMemorySessionService` (per-process). Fine for a single Cloud Run instance;
  for multiple instances or resumable sessions, switch to a persistent session service.
- Single clinic / single timezone / English only / bookings only (no reschedule/cancel).
