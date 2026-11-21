import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AgentSteps from "../components/AgentSteps";
import CompanyLogo from "../components/CompanyLogo";
import { getJson } from "../components/api";
import "./internships.css";

const AGENT_STEPS = [
  "Scout is pulling live internships…",
  "Matcher is scoring them against your profile…",
  "Gemini is writing a reason for each match…",
];
const SWIPE_PX = 110; // drag past this to commit
const FLICK_PX_PER_MS = 0.6; // or flick faster than this
const EXIT_MS = 260; // matches .in-card.leaving transition
const STILL = { dx: 0, dy: 0 };

function firstLocation(address) {
  const parts = (address || "").split(";").map((s) => s.trim()).filter(Boolean);
  if (!parts.length) return "";
  return parts.length > 1 ? `${parts[0]} +${parts.length - 1} more` : parts[0];
}

function JobCard({ job }) {
  const score = job.match?.score;
  return (
    <>
      <div className="in-card-head">
        <CompanyLogo applyUrl={job.apply_url} company={job.company} />
        <div className="in-who">
          <p className="in-company">{job.company}</p>
          <p className="in-loc">{firstLocation(job.address)}</p>
        </div>
        <div className="in-score" style={{ "--score": score ?? 0 }} aria-label={`Match score ${score ?? "unknown"}`}>
          <strong>{score ?? "–"}</strong><span>match</span>
        </div>
      </div>
      <h2>{job.title}</h2>
      {job.match?.reason && <p className="in-reason">{job.match.reason}</p>}
      <a className="in-link" href={job.apply_url} target="_blank" rel="noreferrer">View posting ↗</a>
    </>
  );
}

const Icon = {
  skip: <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>,
  save: <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 12.5l5 5 10-11" /></svg>,
  undo: <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7H4V2" /><path d="M4.5 7A8.5 8.5 0 1 1 3.6 13" /></svg>,
};

export default function Internships() {
  const [remaining, setRemaining] = useState(null); // null = loading; [0] is the top card
  const [total, setTotal] = useState(0);
  const [skipped, setSkipped] = useState([]); // stack, last skip on top; saves aren't undoable (already POSTed)
  const [error, setError] = useState("");
  const [queued, setQueued] = useState(null); // null until GET /queue answers
  const [offset, setOffset] = useState(STILL);
  const [dragging, setDragging] = useState(false);
  const [leaving, setLeaving] = useState(null); // "left" | "right" while the card flies out
  const [returnedId, setReturnedId] = useState(null); // card brought back by Undo, animates in
  const [notice, setNotice] = useState("");
  const drag = useRef(null); // { id, x, y, lastX, lastT, vx } while a pointer is down
  const [reduceMotion] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);

  useEffect(() => {
    let alive = true;
    Promise.all([getJson("/jobs?mode=internship"), getJson("/queue")])
      .then(([jobs, queue]) => {
        if (!alive) return;
        const ids = new Set(queue.map((q) => q.job_id));
        const deck = jobs.filter((j) => !ids.has(j.id)); // already-queued jobs stay off the deck
        setQueued(ids.size);
        setTotal(deck.length);
        setRemaining(deck);
      })
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, []);

  const job = remaining?.[0];

  const decide = useCallback((dir) => {
    if (!job || leaving) return;
    setLeaving(dir);
    setReturnedId(null);
    setNotice("");
    if (dir === "right") {
      getJson(`/queue/${encodeURIComponent(job.id)}`, { method: "POST" })
        .then(() => setQueued((n) => n + 1))
        .catch((e) => setNotice(`Couldn't queue ${job.title}: ${e.message}`));
    }
    setTimeout(() => {
      setRemaining((r) => r.slice(1));
      if (dir === "left") setSkipped((s) => [...s, job]);
      setOffset(STILL);
      setLeaving(null);
    }, reduceMotion ? 0 : EXIT_MS);
  }, [job, leaving, reduceMotion]);

  const undo = useCallback(() => {
    if (leaving || !skipped.length) return;
    const last = skipped[skipped.length - 1];
    setSkipped((s) => s.slice(0, -1));
    setRemaining((r) => [last, ...r]);
    setReturnedId(last.id);
  }, [leaving, skipped]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.closest?.("input, textarea, select")) return;
      if (e.key === "ArrowLeft") decide("left");
      if (e.key === "ArrowRight") decide("right");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [decide]);

  const onPointerDown = (e) => {
    if (leaving || e.button > 0 || e.target.closest("a, button")) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, lastX: e.clientX, lastT: e.timeStamp, vx: 0 };
    setDragging(true);
  };
  const onPointerMove = (e) => {
    const d = drag.current;
    if (d?.id !== e.pointerId) return;
    if (e.timeStamp > d.lastT) d.vx = (e.clientX - d.lastX) / (e.timeStamp - d.lastT);
    d.lastX = e.clientX;
    d.lastT = e.timeStamp;
    setOffset({ dx: e.clientX - d.x, dy: e.clientY - d.y });
  };
  const onPointerEnd = (e) => {
    const d = drag.current;
    if (d?.id !== e.pointerId) return;
    drag.current = null;
    setDragging(false);
    const { dx } = offset;
    const flick = Math.abs(d.vx) > FLICK_PX_PER_MS && Math.abs(dx) > 30 && Math.sign(d.vx) === Math.sign(dx);
    if (e.type === "pointerup" && (Math.abs(dx) > SWIPE_PX || flick)) decide(dx > 0 ? "right" : "left");
    else setOffset(STILL); // springs back via the CSS transition
  };

  const { dx, dy } = offset;
  const pull = leaving ? 1 : Math.min(Math.abs(dx) / SWIPE_PX, 1); // 0..1, how close to committing
  const side = leaving ?? (dx > 0 ? "right" : dx < 0 ? "left" : null);
  const tilt = reduceMotion ? 0 : dx / 18;
  const topTransform = leaving
    ? (reduceMotion ? "none" : `translate(${leaving === "right" ? 120 : -120}vw, ${dy}px) rotate(${leaving === "right" ? 24 : -24}deg)`)
    : `translate(${dx}px, ${dy}px) rotate(${tilt}deg)`;
  const seen = total - (remaining?.length ?? 0);

  return (
    <div className="page in-page">
      <div className="in-column">
        <div className="in-head">
          <h1>Internships</h1>
          <Link to="/queue" className="in-counter">Queued: {queued ?? "…"}</Link>
        </div>

        {error && <p className="in-error" role="alert">Couldn't load internships: {error}</p>}
        {!error && remaining === null && <AgentSteps steps={AGENT_STEPS} />}
        {remaining && !job && (
          <div className="in-empty">
            <p>{total ? "That's every match for now." : "No new internships to review right now."}</p>
            <div className="in-empty-actions">
              <Link to="/queue" className="in-btn in-save">Review your queue</Link>
              {skipped.length > 0 && <button type="button" className="in-btn in-ghost" onClick={undo}>Undo last skip</button>}
            </div>
          </div>
        )}

        {job && (
          <>
            <div className="in-progress">
              <span>{seen + 1} of {total}</span>
              <span className="in-hint">Drag the card, or press ← →</span>
              <div className="in-bar" aria-hidden="true"><div style={{ width: `${(seen / total) * 100}%` }} /></div>
            </div>
            <div className="in-stack">
              {remaining.slice(1, 3).map((j, i) => {
                const depth = i + 1 - pull; // the next card rises as the top one is dragged away
                return (
                  <article
                    key={j.id}
                    className={`in-card in-back${dragging ? " dragging" : ""}`}
                    style={{ transform: `translateY(${depth * 12}px) scale(${1 - depth * 0.05})`, zIndex: 3 - i - 1 }}
                    aria-hidden="true"
                  >
                    <JobCard job={j} />
                  </article>
                );
              }).reverse()}
              <article
                key={job.id}
                className={[
                  "in-card in-top",
                  dragging && "dragging",
                  leaving && "leaving",
                  side && `tint-${side}`,
                  job.id === returnedId && "returned",
                ].filter(Boolean).join(" ")}
                style={{ transform: topTransform, "--pull": pull }}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerEnd}
                onPointerCancel={onPointerEnd}
                aria-label={`${job.title} at ${job.company}`}
              >
                <JobCard job={job} />
                {side && <span className={`in-stamp ${side}`} style={{ opacity: pull }}>{side === "right" ? "SAVE" : "SKIP"}</span>}
              </article>
            </div>
            <div className="in-actions">
              <div className="in-action">
                <button type="button" className="in-round in-skip" onClick={() => decide("left")} disabled={!!leaving} aria-label="Skip (left arrow)">{Icon.skip}</button>
                <span aria-hidden="true">Skip</span>
              </div>
              <div className="in-action">
                <button type="button" className="in-round in-undo" onClick={undo} disabled={!!leaving || !skipped.length} aria-label="Undo last skip">{Icon.undo}</button>
                <span aria-hidden="true">Undo</span>
              </div>
              <div className="in-action">
                <button type="button" className="in-round in-save" onClick={() => decide("right")} disabled={!!leaving} aria-label="Save to queue (right arrow)">{Icon.save}</button>
                <span aria-hidden="true">Save</span>
              </div>
            </div>
          </>
        )}
        {notice && <p className="in-error" role="alert">{notice}</p>}
      </div>
    </div>
  );
}
