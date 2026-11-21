import { useEffect, useState } from "react";
import "../pages/myjob.css";
import { getJson } from "./api";
import { costLabel, groupSteps } from "./routeStyle";

// Drop <TodayCard /> on the home screen. Change refreshKey to reload it after saving a job.
// showShifts lists the leave-by time for every weekly shift (the My Job page turns it on).
export default function TodayCard({ refreshKey = 0, showShifts = false }) {
  const [data, setData] = useState(null);
  const [state, setState] = useState("loading"); // loading | empty | error | ready
  const [error, setError] = useState("");

  useEffect(() => {
    setState("loading");
    getJson("/myjob/today")
      .then((d) => { setData(d); setState("ready"); })
      .catch((e) => {
        if (e.status === 404) return setState("empty");
        setError(e.message); // e.g. 503 "Commute service unavailable: ..." or 502 "No transit route found ..."
        setState("error");
      });
  }, [refreshKey]);

  if (state === "loading") return <section className="mj-today"><p className="mj-muted">Checking your next shift…</p></section>;
  if (state === "empty")
    return <section className="mj-today"><p className="mj-muted">Add your job to see when to leave for your next shift.</p></section>;
  if (state === "error")
    return <section className="mj-today"><p role="alert" className="mj-err">{error}</p></section>;

  const bus = data.steps.find((s) => s.mode === "TRANSIT");
  const walkFirst = groupSteps(data.steps)[0];
  return (
    <section className="mj-today" aria-label="Next shift">
      <p className="mj-muted">Next shift: {data.employer}, {data.shift.day} {data.shift.start}</p>
      <p className="mj-leave"><span>Leave by</span> {data.leave_by}</p>
      <p>
        Arrive by {data.arrive_by} · {data.minutes} min door to door
        {data.origin_label && ` from ${data.origin_label}`} · {costLabel(data)}
      </p>
      {bus ? (
        <p className="mj-muted">
          {walkFirst?.mode === "WALK" && `Walk ${walkFirst.minutes || "under 1"} min, then catch `}
          {walkFirst?.mode !== "WALK" && "Catch "}
          <b>Bus {bus.line}</b> at {bus.from_stop} at {bus.depart}.
        </p>
      ) : (
        <p className="mj-muted">It's a walk, no bus needed.</p>
      )}

      {showShifts && data.shifts?.length > 0 && (
        <table className="mj-shifts">
          <caption>Leave-by time for each shift</caption>
          <thead><tr><th scope="col">Shift</th><th scope="col">Leave by</th><th scope="col">Bus</th></tr></thead>
          <tbody>
            {data.shifts.map((p, i) => (
              <tr key={i}>
                <td>{p.shift.day} {p.shift.start}–{p.shift.end}</td>
                <td>{p.leave_by ?? "—"}</td>
                <td>{p.leave_by ? (p.depart ? `departs ${p.depart}` : "walk") : (p.error ?? "no route")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
