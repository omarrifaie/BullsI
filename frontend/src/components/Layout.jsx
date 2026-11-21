import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import Nav from "./Nav";
import { API, getJson } from "./api";

// GET /health once per mount. Returns { ok: null } while loading, then { ok: true } or { ok: false, error }.
export function useHealth() {
  const [health, setHealth] = useState({ ok: null });
  useEffect(() => {
    let alive = true;
    getJson("/health")
      .then((body) => alive && setHealth(body?.ok ? { ok: true } : { ok: false, error: "Backend reported not ok." }))
      .catch((e) => alive && setHealth({ ok: false, error: e.message }));
    return () => { alive = false; };
  }, []);
  return health;
}

// "Backend status" line for the placeholder pages.
export function BackendStatus() {
  const { ok, error } = useHealth();
  const text = ok === null ? "checking…" : ok ? "ok" : error;
  return <p className="status">Backend status: <span className={ok === false ? "status-bad" : ""}>{text}</span></p>;
}

export default function Layout() {
  const { ok } = useHealth();
  return (
    <div className="app">
      <Nav />
      {ok === false && (
        <div className="banner" role="alert">
          Backend not reachable at {API}. Start it with the command in backend/README.md.
        </div>
      )}
      <main className="shell">
        <Outlet />
      </main>
    </div>
  );
}
