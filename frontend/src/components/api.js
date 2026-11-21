// Backend base URL for the part-time and My Job pages. Set VITE_API_URL in frontend/.env.
const FALLBACK_API = "http://localhost:8000";

export const API = import.meta.env.VITE_API_URL || warnFallback();

function warnFallback() {
  console.warn(`VITE_API_URL isn't set in frontend/.env; using ${FALLBACK_API} (local dev only).`);
  return FALLBACK_API;
}

// fetch + JSON. Throws an Error carrying the backend's `detail` (e.g. a 503's reason) and the HTTP status.
export async function getJson(path, init) {
  const res = await fetch(`${API}${path}`, init);
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    // FastAPI validation errors (422) send `detail` as a list of objects, not a string.
    const detail = typeof body?.detail === "string" ? body.detail : body?.detail && JSON.stringify(body.detail);
    const err = new Error(detail || `Request failed (${res.status}).`);
    err.status = res.status;
    throw err;
  }
  return body;
}
