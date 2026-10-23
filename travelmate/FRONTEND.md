# TravelMate frontend + API

From this project directory, run:

    uv sync --extra dev
    uv run uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000

Open http://127.0.0.1:8000. FastAPI serves both UI and API on the same origin.
Do not open the HTML through file://. Original Figma prototype sources remain in outputs.

Connected screens: home → create → loading → plan → day; explore; session plan list.
Create submits POST /api/v1/plans/preview. Explore submits POST /api/v1/places/search.
Date, group size, budget, interests and notes are sent to the backend. Warnings and unknown costs remain visible.

Default mode is demo with fictional places. Live mode currently requires Gemini, Maps and backend access token configuration; a Gemini key alone does not enable live place search. The separate specialist agent CLIs are not exposed by these endpoints.
Provider keys belong only in the server environment. If TRAVELMATE_API_TOKEN is set, enter that token in the UI connection panel. It is retained only in sessionStorage for that tab.

Plans are retained in sessionStorage (up to 20); there is no account/database persistence yet. Auth, chat, reviews, favorites and administration screens show an explicit unavailable state until backend endpoints exist. API does not return images, so result screens do not invent hotel/place photos.

Source: frontend/travelmate-v2; local assets: frontend/travelmate-ui/assets. Existing design CSS is reused.
Browser integration smoke: tests/frontend-smoke.cjs (local bundled Playwright and Edge; BASE_URL defaults to port 8012).
