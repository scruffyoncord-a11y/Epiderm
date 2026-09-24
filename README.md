# Epiderm

Explainable trust and impersonation risk assessment (Innovators Conclave 2026, PS-02).

## Landing page

The standalone Epiderm marketing website is in [`website/`](website/). It is a single responsive HTML page and does not require a build step. See [`website/README.md`](website/README.md) for local preview instructions.

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
