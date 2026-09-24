# TrustGuard

Explainable trust and impersonation risk assessment (Innovators Conclave 2026, PS-02).

## Run

Backend (port 8001):

    cd backend
    pip install -r requirements.txt
    python -m uvicorn app.main:app --port 8001
    python -m pytest -q

Frontend (port 3000):

    cd frontend
    npm install
    npm run dev

The frontend reads `NEXT_PUBLIC_API_URL` from `frontend/.env.local` (default `http://127.0.0.1:8001`).

## Layout

- `backend/app/models.py` - the shared contracts: `Signal`, `ConsistencyCheck`, `Event`, `Scenario`, `Analysis`.
- `backend/scenarios/` - four simulated test scenarios with their expected decision band.
- `backend/tests/` - Phase 0 checks (contract round trip, scenarios load, endpoints).
- `frontend/` - Next.js app.

All session data in the scenarios (IP, device, location) is simulated and labelled as such.

## Private sandbox (Docker)

When a person picks a category, the app opens their own private container (the ripple loader shows
"Opening a private container..." until it is ready). Every uploaded file and every pasted block of email
headers they check is parsed inside it. It has no network, a read-only filesystem, no privileges, a 256 MB
memory cap, a process cap and a 30 second limit per check, and runs as a non-root user. Only a small JSON
result comes back, and the main server validates it again. If the sandbox fails on a file, the file is
refused; it is never parsed outside the sandbox instead.

The container is deleted when the person leaves the screen or closes the tab (the browser sends a close
request), after 10 idle minutes (`TRUSTGUARD_SESSION_IDLE_SECONDS`), or when the server stops. At most 6
sessions are open at once (`TRUSTGUARD_MAX_SESSIONS`); the least recently used is closed to make room. Each
person has a separate container. If a session's container dies, the next check runs in a fresh one-off
container.

A session container handles several checks, so it is slightly less strict than one container per file: a
malicious file could affect later files in the same person's session. It still cannot reach the network,
the host, or anyone else's session.

Build the image once (needs Docker Desktop running), and again whenever the parsing code changes:

    cd backend
    docker build -f Dockerfile.sandbox -t trustguard-sandbox .

`TRUSTGUARD_SANDBOX` in `backend/.env`: `auto` (default: use it when the image is ready, and say so on
screen if not), `docker` (require it; requests fail with 503 if it is missing), or `off`.

What it does not cover: the AI model call (Ollama, on the host) and plain message text, which is not
parsed. The main app deliberately does not run inside Docker, because that would need the Docker socket
mounted, which gives a compromised app control of the machine.
