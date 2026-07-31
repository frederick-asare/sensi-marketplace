# Sensi Farmer-to-Buyer Marketplace (Group 2)

Minimal Flask app: user registration/login, create a listing (title, price,
description, photo), and a public listings page. Built to sit behind the
ModSecurity WAF and Wazuh monitoring stack from the CY174 report.

## Run locally (no Docker, quick check)
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Visit http://localhost:3000

## Run with Docker only (app container by itself)
```bash
docker build -t sensi-app .
docker run -p 3000:3000 sensi-app
```
Visit http://localhost:3000

## Run with Docker Compose (app + WAF, matches the report architecture)
```bash
docker compose up --build
```
Visit http://localhost (port 80, traffic goes through the WAF first)

## Notes for the CY174 report
- `/healthz` — simple health check endpoint, useful to confirm the container
  is up before adding the WAF in front of it.
- Uploads are restricted to `png/jpg/jpeg/gif` and capped at 5 MB
  (`MAX_CONTENT_LENGTH` in `app.py`) — mention this as an application-layer
  control in Task 2/3, alongside the WAF and Wazuh file-integrity monitoring.
- For the Task 4 "malicious file upload" test, try uploading a `.php` or
  `.exe` file renamed to `.jpg` — the extension check should reject it, and
  you can discuss in your report what it does and doesn't catch (it checks
  the extension, not file content — a good point to raise as a limitation).
- For the Task 4 brute-force test, the login route has no rate limiting at
  the app level on purpose — this is intentional so the Wazuh custom rule
  (frequency=5, timeframe=120s) is what catches it, not the app itself.
  Mention this design choice in your report.
- SQLite is used for simplicity. If you want to match the earlier
  `docker-compose.yml` draft that used Postgres instead, swap
  `SQLALCHEMY_DATABASE_URI` to a Postgres connection string and add a `db`
  service back to `docker-compose.yml`.

## Next steps once deployed to AWS
1. Confirm `docker compose up --build` works locally first
2. Push this project to your EC2 instance (git clone, or scp)
3. Run `docker compose up -d --build` on the EC2 host
4. Confirm reachable via the EC2 public IP on port 80
5. Then move on to Wazuh manager/agent setup per the roadmap
