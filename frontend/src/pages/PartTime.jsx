import { useEffect, useMemo, useState } from "react";
import RouteMap from "../components/RouteMap";
import { getJson } from "../components/api";
import { WALK_COLOR, costLabel, groupSteps, lineColors, usesTransit } from "../components/routeStyle";
import "./parttime.css";

const fmtShift = (s) => `${s.day} ${s.start}–${s.end}`;
const fromLabel = (c) => (c?.origin_label ? `from ${c.origin_label}` : "");

function JobRow({ job, onOpen, active }) {
  const c = job.commute ?? {};
  const hasRoute = c.minutes != null;
  const how = usesTransit(c.steps) ? "by bus" : "on foot";
  return (
    <li className={`pt-row${active ? " is-active" : ""}`}>
      <div className="pt-time" aria-label={hasRoute ? `${c.minutes} minutes ${how} ${fromLabel(c)}` : "No route found"}>
        {hasRoute ? (
          <>
            <span className="pt-min">{c.minutes}</span>
            <span className="pt-unit">min {how}</span>
            <span className="pt-unit">{fromLabel(c)}</span>
          </>
        ) : (
          <span className="pt-unit">No route found</span>
        )}
      </div>

      <div className="pt-main">
        <h3>{job.title}</h3>
        <p className="pt-meta">
          {[job.company, job.pay != null && `$${job.pay.toFixed(2)}/hr`, job.shifts?.map(fmtShift).join(", ")]
            .filter(Boolean).join(" · ")}
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

function Co2Source({ source }) {
  if (!source) return null;
  return (
    <a className="pt-source" href={source.url} target="_blank" rel="noreferrer">{source.label}</a>
  );
}

function DetailsPanel({ job, onClose }) {
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setDetail(null);
    setErr("");
    getJson(`/jobs/${encodeURIComponent(job.id)}/commute`).then(setDetail).catch((e) => setErr(e.message));
  }, [job.id]);

  const steps = detail?.steps ?? [];
  const colors = useMemo(() => lineColors(steps), [steps]);
  const noRoute = detail && detail.minutes == null;
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
      {noRoute && (
        <p role="alert" className="pt-err">
          No route right now{detail.error ? `: ${detail.error}` : ". Google found no transit or walking route for this shift."}
        </p>
      )}

      {detail && !noRoute && (
        <>
          <RouteMap steps={steps} />
          {colors.size > 0 && (
            <ul className="pt-legend" aria-label="Map legend">
              {[...colors].map(([line, color]) => (
                <li key={line}><span className="pt-swatch" style={{ background: color }} />Bus {line}</li>
              ))}
              <li><span className="pt-swatch is-walk" style={{ borderColor: WALK_COLOR }} />Walk</li>
            </ul>
          )}

          <p className="pt-arrive">
            Leave {fromLabel(detail)} by <strong>{detail.leave_by}</strong> to arrive by <strong>{detail.arrive_by}</strong>
            {detail.next_shift && <> for your {fmtShift(detail.next_shift)} shift</>}.
          </p>

          <ol className="pt-steps">
            {groupSteps(steps).map((s, i) => (
              <li key={i} className={s.mode === "TRANSIT" ? "is-bus" : "is-walk"}>
                <span className="pt-clock">{s.depart || ""}</span>
                <span className="pt-dot" style={s.mode === "TRANSIT" ? { background: colors.get(s.line) } : undefined} />
                <span className="pt-what">
                  {s.mode === "TRANSIT" ? (
                    <>
                      <b>Bus {s.line}</b> toward {s.headsign || "end of line"}
                      <small>{s.from_stop} → {s.to_stop} · {s.stops} stops · arrives {s.arrive}</small>
                      {s.fare_note && <small>{s.fare_note}</small>}
                    </>
                  ) : (
                    <>Walk {s.minutes ? `${s.minutes} min` : "under 1 min"}</>
                  )}
                </span>
              </li>
            ))}
          </ol>

          <dl className="pt-facts">
            <div><dt>Cost</dt><dd>{costLabel(detail)}</dd></div>
            <div><dt>Transfers</dt><dd>{detail.transfers}</dd></div>
            <div>
              <dt>CO₂ saved per week</dt>
              <dd>
                {detail.car_free ? `${detail.co2_saved_kg_week} kg vs. driving` : "Not car-free"}
                {detail.car_free && <Co2Source source={detail.co2_source} />}
              </dd>
            </div>
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
    getJson("/jobs?mode=parttime")
      .then((data) => setJobs(Array.isArray(data) ? data : []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const shown = useMemo(() => (carFreeOnly ? jobs.filter((j) => j.commute?.car_free) : jobs), [jobs, carFreeOnly]);
  const best = useMemo(
    () => jobs.filter((j) => j.commute?.car_free)
      .reduce((top, j) => (j.commute.co2_saved_kg_week > (top?.commute.co2_saved_kg_week ?? 0) ? j : top), null),
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
        {best && (
          <p className="pt-meta">
            Best car-free pick saves up to {best.commute.co2_saved_kg_week} kg of CO₂ a week.{" "}
            <Co2Source source={best.commute.co2_source} />
          </p>
        )}

        {loading && <p className="pt-meta">Finding jobs around your schedule…</p>}
        {error && <p role="alert" className="pt-err">{error}</p>}
        {!loading && !error && jobs.length === 0 && (
          <p className="pt-meta">Every part-time job we found has shifts that overlap your classes. Check back soon.</p>
        )}
        {!loading && !error && jobs.length > 0 && shown.length === 0 && (
          <p className="pt-meta">None of these jobs are car-free. Turn off “Car-free only” to see every job that fits your schedule.</p>
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
