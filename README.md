# BullPen (HackJam)

## Frontend (`frontend/`)

Vite + React on http://localhost:5173. From `frontend/`:

```powershell
copy .env.example .env   # then set VITE_API_URL=http://localhost:8000 and VITE_GOOGLE_MAPS_KEY=...
npm install
npm run dev
```

Start the backend first (see `backend/README.md`); the app shows a banner when it can't reach `/health`.
