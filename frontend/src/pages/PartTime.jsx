import { useEffect, useMemo, useState } from "react";
import RouteMap from "../components/RouteMap";
import "./parttime.css";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

const fmtShift = (s) => `${s.day} ${s.start}–${s.end}`;

function JobRow({ job, onOpen, active }) {
  const c = job.commute ?? {};
  const hasRoute = c.minutes != null;
  return (
    <li className={`pt-row${active ? " is-active" : ""}`}>
      <div className="pt-time" aria-label={hasRoute ? `${c.minutes} minutes by bus` : "No bus route"}>
        {hasRoute ? (
          <>
            <span className="pt-min">{c.minutes}</span>
            <span className="pt-unit">min by bus</span>
          </>
        ) : (
          <span className="pt-unit">No bus route found</span>
        )}
      </div>

      <div className="pt-main">
        <h3>{job.title}</h3>
        <p className="pt-meta">
          {job.company} · ${job.pay?.toFixed(2)}/hr · {job.shifts?.map(fmtShift).join(", ")}
        </p>
        {job.match?.reason && <p className="pt-reason">{job.match.reason}</p>}
      </div>

      <div className="pt-side">
        <span className="pt-score" title="Match score">{job.match?.score}</span>
        {c.car_free && <span className="pt-badge">✓ Car-free</span>}
        <button type="button" className="pt-link" onClick={() => onOpen(job)} disabled={!hasRoute}>
          Route details
        </button>
      </div>
    </li>
  );
}

function DetailsPanel({ job, onClose }) {
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setDetail(null);
    setErr("");
    fetch(`${API}/jobs/${job.id}/commute`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("Could not load the route."))))
      .then(setDetail)
      .catch((e) => setErr(e.message));
  }, [job.id]);

  const steps = detail?.steps ?? [];
  return (
    <aside className="pt-panel" aria-label={`Route to ${job.company}`}>
      <header>
        <div>
          <h2>{job.company}</h2>
          <p className="pt-meta">{job.address}</p>
        </div>
        <button type="button" className="pt-close" onClick={onClose} aria-label="Close route details">×</button>
      </header>

      {err && <p role="alert" className="pt-err">{err}</p>}
      {!detail && !err && <p className="pt-meta">Loading route…</p>}

      {detail && (
        <>
          <RouteMap steps={steps} />

          <p className="pt-arrive">
            Leave by <strong>{detail.leave_by}</strong> to arrive by <strong>{detail.arrive_by}</strong>
            {detail.next_shift && <> for your {fmtShift(detail.next_shift)} shift</>}.
          </p>

          <ol className="pt-steps">
            {steps.map((s, i) => (
              <li key={i} className={s.mode === "TRANSIT" ? "is-bus" : "is-walk"}>
                <span className="pt-clock">{s.depart || ""}</span>
                <span className="pt-dot" style={s.mode === "TRANSIT" ? { background: s.color } : undefined} />
                <span className="pt-what">
                  {s.mode === "TRANSIT" ? (
                    <>
                      <b>{s.line}</b> {s.instruction.replace(/^Take \S+ /, "")}
                      <small>{s.from_stop} → {s.to_stop} · {s.stops} stops · arrives {s.arrive}</small>
                    </>
                  ) : (
                    <>{s.instruction}<small>{s.minutes} min on foot</small></>
                  )}
                </span>
              </li>
            ))}
          </ol>

          <dl className="pt-facts">
            <div><dt>Cost</dt><dd>{detail.cost_usd === 0 ? "Free with USFCard" : `$${detail.cost_usd?.toFixed(2)} per ride`}</dd></div>
            <div><dt>Transfers</dt><dd>{detail.transfers}</dd></div>
            <div><dt>CO₂ saved per week</dt><dd>{detail.co2_saved_kg_week} kg vs. driving</dd></div>
          </dl>
        </>
      )}
    </aside>
  );
}

export default function PartTime() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [carFreeOnly, setCarFreeOnly] = useState(false);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    fetch(`${API}/jobs?mode=parttime`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("Could not load jobs."))))
      .then((data) => setJobs(Array.isArray(data) ? data : data.jobs ?? []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const shown = useMemo(
    () => (carFreeOnly ? jobs.filter((j) => j.commute?.car_free) : jobs),
    [jobs, carFreeOnly]
  );
  const weeklyCo2 = useMemo(
    () => jobs.filter((j) => j.commute?.car_free).reduce((m, j) => Math.max(m, j.commute.co2_saved_kg_week || 0), 0),
    [jobs]
  );

  return (
    <main className={`pt-page${open ? " has-panel" : ""}`}>
      <section className="pt-list">
        <div className="pt-head">
          <h1>Jobs that fit your classes and your bus pass</h1>
          <label className="pt-toggle">
            <input type="checkbox" checked={carFreeOnly} onChange={(e) => setCarFreeOnly(e.target.checked)} />
            Car-free only
          </label>
        </div>
        {weeklyCo2 > 0 && <p className="pt-meta">Best car-free pick saves up to {weeklyCo2} kg of CO₂ a week.</p>}

        {loading && <p className="pt-meta">Finding jobs around your schedule…</p>}
        {error && <p role="alert" className="pt-err">{error}</p>}
        {!loading && !error && shown.length === 0 && (
          <p className="pt-meta">No jobs match. Turn off “Car-free only” to see every job that fits your schedule.</p>
        )}

        <ul>
          {shown.map((j) => (
            <JobRow key={j.id} job={j} active={open?.id === j.id} onOpen={setOpen} />
          ))}
        </ul>
      </section>

      {open && <DetailsPanel job={open} onClose={() => setOpen(null)} />}
    </main>
  );
}
