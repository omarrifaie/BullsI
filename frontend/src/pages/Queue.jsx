import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AgentSteps from "../components/AgentSteps";
import { getJson } from "../components/api";
import "./queue.css";

const PREPARE_STEPS = [
  "Reading each job description…",
  "Gemini is tailoring your resume and cover letter…",
  "Compiling the PDFs…",
];
const STATUS_LABELS = { ready: "Prepared", not_prepared: "Not prepared", error: "Error" };
const APPLY_LABELS = {
  opening: "Opening",
  waiting_for_signin: "Waiting for you to sign in",
  filling: "Filling",
  ready_for_review: "Ready for your review",
  error: "Error",
};
const POLL_MS = 2000;
const isDone = (jobs) => jobs.length > 0 && jobs.every((j) => j.status === "ready_for_review" || j.status === "error");

function Documents({ item }) {
  return (
    <div className="q-docs">
      <div className="q-pdfs">
        {[["Resume", item.resume_url], ["Cover letter", item.cover_letter_url]].map(([label, url]) => url && (
          <figure key={label}>
            <figcaption><a href={url} target="_blank" rel="noreferrer">{label} ↗</a></figcaption>
            <iframe src={url} title={`${label} for ${item.title}`} loading="lazy" />
          </figure>
        ))}
      </div>
      {item.warnings.length > 0 && (
        <ul className="q-warnings">{item.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
      )}
    </div>
  );
}

export default function Queue() {
  const [items, setItems] = useState(null); // null = loading
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(null); // "prepare" | "auto" while a slow call runs
  const [threshold, setThreshold] = useState(80);
  const [notice, setNotice] = useState("");
  const [applyJobs, setApplyJobs] = useState(null); // null until Apply is clicked
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true; // StrictMode re-runs effects after a fake unmount
    return () => { alive.current = false; };
  }, []);

  // /queue has no score, so join with the (cached) ranked internships.
  const load = useCallback(async () => {
    const [queue, jobs] = await Promise.all([getJson("/queue"), getJson("/jobs?mode=internship").catch(() => [])]);
    const scores = new Map(jobs.map((j) => [j.id, j.match?.score]));
    return queue.map((q) => ({ ...q, score: scores.get(q.job_id), cached: false, error: null }));
  }, []);

  useEffect(() => {
    load().then((list) => alive.current && setItems(list)).catch((e) => alive.current && setError(e.message));
  }, [load]);

  // Fold /prepare or /auto documents (they carry `cached` and `error`) into a fresh /queue read.
  async function run(kind) {
    setBusy(kind);
    setNotice("");
    try {
      const body = kind === "auto"
        ? await getJson(`/auto?threshold=${threshold}`, { method: "POST" })
        : await getJson("/prepare", { method: "POST" });
      const docs = new Map(body.documents.map((d) => [d.job_id, d]));
      const list = await load();
      if (!alive.current) return;
      setItems(list.map((q) => (docs.has(q.job_id) ? { ...q, ...docs.get(q.job_id), title: q.title, company: q.company } : q)));
      if (kind === "auto") setNotice(`Auto mode queued ${body.queued.length} internship(s) scoring ${threshold}+.`);
    } catch (e) {
      if (alive.current) setNotice(`Couldn't ${kind === "auto" ? "auto-prepare" : "prepare documents"}: ${e.message}`);
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  async function remove(jobId) {
    try {
      await getJson(`/queue/${encodeURIComponent(jobId)}`, { method: "DELETE" });
      setItems((list) => list.filter((q) => q.job_id !== jobId));
    } catch (e) {
      setNotice(`Couldn't remove it: ${e.message}`);
    }
  }

  // POST /apply, then poll /apply/status every 2 s (one request at a time) until every tab is done or we leave.
  async function apply() {
    setNotice("");
    try {
      const { status } = await getJson("/apply", { method: "POST" });
      if (status === "already_running") setNotice("The application browser is already open.");
      setApplyJobs([]);
      while (alive.current) {
        const { jobs } = await getJson("/apply/status");
        if (!alive.current) return;
        setApplyJobs(jobs);
        if (isDone(jobs)) return;
        await new Promise((r) => setTimeout(r, POLL_MS));
      }
    } catch (e) {
      if (alive.current) setNotice(`Couldn't start applying: ${e.message}`);
    }
  }

  const titles = new Map((items ?? []).map((q) => [q.job_id, q]));
  const prepared = (items ?? []).filter((q) => q.resume_url || q.cover_letter_url);

  return (
    <div className="page q-page">
      <h1>Application queue</h1>
      <p>Prepare tailored resumes and cover letters, then let BullPen fill the applications for you to review.</p>

      {error && <p className="q-error" role="alert">Couldn't load your queue: {error}</p>}
      {!error && items === null && <p className="status">Loading your queue…</p>}
      {items?.length === 0 && (
        <div className="q-empty">
          <p>Your queue is empty.</p>
          <Link to="/internships">Swipe through internships</Link> to add some, or use auto mode below.
        </div>
      )}

      {items && (
        <>
          <section className="q-controls" aria-label="Prepare documents">
            <button type="button" className="q-btn" onClick={() => run("prepare")} disabled={!!busy || !items.length}>
              Prepare documents
            </button>
            <div className="q-auto">
              <label htmlFor="q-threshold">Auto mode: queue and prepare every internship scoring <strong>{threshold}+</strong></label>
              <div className="q-auto-row">
                <input id="q-threshold" type="range" min="50" max="100" step="5" value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))} disabled={!!busy} />
                <button type="button" className="q-btn q-btn-ghost" onClick={() => run("auto")} disabled={!!busy}>
                  Auto-prepare
                </button>
              </div>
            </div>
          </section>
          {busy && <AgentSteps steps={PREPARE_STEPS} everyMs={5000} />}
          {notice && <p className="q-notice" role="status">{notice}</p>}

          <section className="q-apply" aria-label="Apply">
            <h2>Apply</h2>
            <p className="q-apply-note">
              BullPen opens each application in a browser window and fills what your profile answers.
              <strong> It never submits.</strong> You review every application and click Submit yourself.
            </p>
            <button type="button" className="q-btn" onClick={apply} disabled={!prepared.length || (applyJobs && !isDone(applyJobs))}>
              Open and fill applications
            </button>
            {applyJobs && (
              <ul className="q-apply-list" aria-live="polite">
                {applyJobs.length === 0 && <li className="status">Starting the browser…</li>}
                {applyJobs.map((j) => (
                  <li key={j.job_id}>
                    <div className="q-row">
                      <div className="q-title">
                        <strong>{titles.get(j.job_id)?.title ?? j.job_id}</strong>
                        <span>{titles.get(j.job_id)?.company}</span>
                      </div>
                      <span className={`q-chip q-apply-${j.status}`}>{APPLY_LABELS[j.status] ?? j.status}</span>
                      <span className="q-filled">{j.filled_count} filled</span>
                    </div>
                    {j.needs_you?.length > 0 && (
                      <p className="q-needs"><strong>Needs you:</strong> {j.needs_you.join(", ")}</p>
                    )}
                    {j.error && <p className="q-error">{j.error}</p>}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <ul className="q-list">
            {items.map((q) => (
              <li key={q.job_id} className="q-item">
                <div className="q-row">
                  <div className="q-score" aria-label={`Match score ${q.score ?? "unknown"}`}>{q.score ?? "–"}</div>
                  <div className="q-title">
                    <strong>{q.title}</strong>
                    <span>{q.company}</span>
                  </div>
                  <span className={`q-chip q-st-${q.status}`}>{STATUS_LABELS[q.status] ?? q.status}</span>
                  {q.cached && <span className="q-chip q-cached">cached</span>}
                  <button type="button" className="q-remove" onClick={() => remove(q.job_id)} disabled={!!busy}
                    aria-label={`Remove ${q.title} from queue`}>Remove</button>
                </div>
                {q.error && <p className="q-error">{q.error}</p>}
                {(q.resume_url || q.cover_letter_url) && <Documents item={q} />}
              </li>
            ))}
          </ul>

        </>
      )}
    </div>
  );
}
