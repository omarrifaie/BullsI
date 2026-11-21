import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AgentSteps from "../components/AgentSteps";
import { getJson } from "../components/api";
import "./internships.css";

const AGENT_STEPS = [
  "Scout is pulling live internships…",
  "Matcher is scoring them against your profile…",
  "Gemini is writing a reason for each match…",
];
const SWIPE_PX = 120; // drag past this to commit
const EXIT_MS = 220; // matches .in-card.leaving transition

export default function Internships() {
  const [deck, setDeck] = useState(null); // null = loading
  const [error, setError] = useState("");
  const [queued, setQueued] = useState(null); // null until GET /queue answers
  const [index, setIndex] = useState(0);
  const [dx, setDx] = useState(0);
  const [leaving, setLeaving] = useState(null); // "left" | "right" while the card animates out
  const [notice, setNotice] = useState("");
  const drag = useRef(null); // { id, startX } while a pointer is down

  useEffect(() => {
    let alive = true;
    Promise.all([getJson("/jobs?mode=internship"), getJson("/queue")])
      .then(([jobs, queue]) => {
        if (!alive) return;
        const ids = new Set(queue.map((q) => q.job_id));
        setQueued(ids.size);
        setDeck(jobs.filter((j) => !ids.has(j.id))); // already-queued jobs stay off the deck
      })
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, []);

  const job = deck?.[index];

  const decide = useCallback((dir) => {
    if (!job || leaving) return;
    setLeaving(dir);
    setNotice("");
    if (dir === "right") {
      getJson(`/queue/${encodeURIComponent(job.id)}`, { method: "POST" })
        .then(() => setQueued((n) => n + 1))
        .catch((e) => setNotice(`Couldn't queue ${job.title}: ${e.message}`));
    }
    setTimeout(() => {
      setIndex((i) => i + 1);
      setDx(0);
      setLeaving(null);
    }, EXIT_MS);
  }, [job, leaving]);

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
    drag.current = { id: e.pointerId, startX: e.clientX };
  };
  const onPointerMove = (e) => {
    if (drag.current?.id === e.pointerId) setDx(e.clientX - drag.current.startX);
  };
  const onPointerEnd = (e) => {
    if (drag.current?.id !== e.pointerId) return;
    drag.current = null;
    if (Math.abs(dx) > SWIPE_PX) decide(dx > 0 ? "right" : "left");
    else setDx(0);
  };

  const transform = leaving
    ? `translateX(${leaving === "right" ? 140 : -140}%) rotate(${leaving === "right" ? 18 : -18}deg)`
    : `translateX(${dx}px) rotate(${dx / 20}deg)`;
  const hint = leaving ?? (dx > SWIPE_PX / 2 ? "right" : dx < -SWIPE_PX / 2 ? "left" : null);

  return (
    <div className="page in-page">
      <div className="in-head">
        <h1>Internships</h1>
        <Link to="/queue" className="in-counter">Queued: {queued ?? "…"}</Link>
      </div>
      <p>Swipe right (or press →) to save to your queue, left (←) to skip.</p>

      {error && <p className="in-error" role="alert">Couldn't load internships: {error}</p>}
      {!error && deck === null && <AgentSteps steps={AGENT_STEPS} />}
      {deck && !job && (
        <div className="in-empty">
          <p>{deck.length ? "That's every match for now." : "No new internships to review right now."}</p>
          <Link to="/queue" className="in-btn in-save">Review your queue</Link>
        </div>
      )}

      {job && (
        <>
          <p className="status in-count">{index + 1} of {deck.length}</p>
          <div className="in-stage">
            <article
              key={job.id}
              className={`in-card${leaving ? " leaving" : ""}${dx && !leaving ? " dragging" : ""}`}
              style={{ transform }}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerEnd}
              onPointerCancel={onPointerEnd}
              aria-label={`${job.title} at ${job.company}`}
            >
              {hint && <span className={`in-stamp ${hint}`}>{hint === "right" ? "SAVE" : "SKIP"}</span>}
              <div className="in-score" aria-label={`Match score ${job.match?.score ?? "unknown"}`}>
                <strong>{job.match?.score ?? "–"}</strong><span>match</span>
              </div>
              <h2>{job.title}</h2>
              <p className="in-company">{job.company}</p>
              <p className="in-loc">{job.address}</p>
              {job.match?.reason && <p className="in-reason">{job.match.reason}</p>}
              <a href={job.apply_url} target="_blank" rel="noreferrer">View posting ↗</a>
            </article>
          </div>
          <div className="in-actions">
            <button type="button" className="in-btn in-skip" onClick={() => decide("left")} disabled={!!leaving}>Skip</button>
            <button type="button" className="in-btn in-save" onClick={() => decide("right")} disabled={!!leaving}>Save</button>
          </div>
        </>
      )}
      {notice && <p className="in-error" role="alert">{notice}</p>}
    </div>
  );
}
