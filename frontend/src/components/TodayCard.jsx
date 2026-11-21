import { useEffect, useState } from "react";
import "../pages/myjob.css";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// Drop <TodayCard /> on Person C's home screen. Change refreshKey to reload it after saving a job.
export default function TodayCard({ refreshKey = 0 }) {
  const [data, setData] = useState(null);
  const [state, setState] = useState("loading"); // loading | empty | error | ready

  useEffect(() => {
    setState("loading");
    fetch(`${API}/myjob/today`)
      .then(async (r) => {
        if (r.status === 404) return setState("empty");
        if (!r.ok) throw new Error("bad response");
        setData(await r.json());
        setState("ready");
      })
      .catch(() => setState("error"));
  }, [refreshKey]);

  if (state === "loading") return <section className="mj-today"><p className="mj-muted">Checking your next shift…</p></section>;
  if (state === "empty")
    return <section className="mj-today"><p className="mj-muted">Add your job to see when to leave for your next shift.</p></section>;
  if (state === "error")
    return <section className="mj-today"><p role="alert" className="mj-err">Couldn’t find a bus route for your next shift. Try again in a minute.</p></section>;

  const bus = data.steps.find((s) => s.mode === "TRANSIT");
  return (
    <section className="mj-today" aria-label="Next shift">
      <p className="mj-muted">Next shift: {data.employer}, {data.shift.day} {data.shift.start}</p>
      <p className="mj-leave"><span>Leave by</span> {data.leave_by}</p>
      <p>
        Arrive by {data.arrive_by} · {data.minutes} min door to door
        {data.cost_usd === 0 ? " · free with USFCard" : data.cost_usd ? ` · $${data.cost_usd.toFixed(2)}` : ""}
      </p>
      {bus && (
        <p className="mj-muted">
          Catch the <b>{bus.line}</b> at {bus.from_stop} at {bus.depart}.
        </p>
      )}
      <a className="mj-btn" href={`${API}/myjob/calendar.ics`}>Add leave-by reminders to my calendar</a>
    </section>
  );
}
