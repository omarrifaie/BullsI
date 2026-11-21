import { useEffect, useState } from "react";
import TodayCard from "../components/TodayCard";
import "./myjob.css";
import { API } from "../components/api";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const blankShift = () => ({ day: "Tue", start: "15:00", end: "21:00" });

export default function MyJob() {
  const [form, setForm] = useState({ employer: "", address: "", home_address: "", shifts: [blankShift()] });
  const [status, setStatus] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [chat, setChat] = useState([]);
  const [msg, setMsg] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    fetch(`${API}/myjob`)
      .then((r) => r.json())
      .then((j) => j.employer && setForm({ ...j, home_address: j.home_address ?? "" }))
      .catch(() => {});
  }, []);

  const setShift = (i, patch) =>
    setForm((f) => ({ ...f, shifts: f.shifts.map((s, n) => (n === i ? { ...s, ...patch } : s)) }));

  async function save(e) {
    e.preventDefault();
    setStatus("Saving…");
    try {
      const r = await fetch(`${API}/myjob`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, home_address: form.home_address || null }),
      });
      if (!r.ok) throw new Error();
      setStatus("Saved. Your leave-by time is updated.");
      setRefreshKey((k) => k + 1);
    } catch {
      setStatus("Couldn’t save. Check that the backend is running.");
    }
  }

  async function send(text) {
    if (!text.trim() || sending) return;
    setChat((c) => [...c, { from: "me", text }]);
    setMsg("");
    setSending(true);
    try {
      const r = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const j = await r.json();
      setChat((c) => [...c, { from: "bot", text: j.reply ?? "No answer. Check the HART app for live departures." }]);
    } catch {
      setChat((c) => [...c, { from: "bot", text: "I couldn’t reach the route service. Check the HART app for live departures." }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="mj-page">
      <h1>My job</h1>
      <TodayCard refreshKey={refreshKey} />

      <form onSubmit={save} className="mj-form">
        <h2>Where and when you work</h2>
        <label>Employer
          <input required value={form.employer} onChange={(e) => setForm({ ...form, employer: e.target.value })} />
        </label>
        <label>Work address
          <input required value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
        </label>
        <label>Leaving from (optional, defaults to your profile address)
          <input value={form.home_address} onChange={(e) => setForm({ ...form, home_address: e.target.value })} />
        </label>

        <fieldset>
          <legend>Shifts</legend>
          {form.shifts.map((s, i) => (
            <div className="mj-shift" key={i}>
              <select value={s.day} onChange={(e) => setShift(i, { day: e.target.value })} aria-label="Day">
                {DAYS.map((d) => <option key={d}>{d}</option>)}
              </select>
              <input type="time" value={s.start} onChange={(e) => setShift(i, { start: e.target.value })} aria-label="Start time" />
              <input type="time" value={s.end} onChange={(e) => setShift(i, { end: e.target.value })} aria-label="End time" />
              {form.shifts.length > 1 && (
                <button type="button" className="mj-x" aria-label="Remove shift"
                  onClick={() => setForm((f) => ({ ...f, shifts: f.shifts.filter((_, n) => n !== i) }))}>×</button>
              )}
            </div>
          ))}
          <button type="button" className="mj-link" onClick={() => setForm((f) => ({ ...f, shifts: [...f.shifts, blankShift()] }))}>
            Add another shift
          </button>
        </fieldset>

        <button className="mj-btn" type="submit">Save job</button>
        {status && <p role="status" className="mj-muted">{status}</p>}
      </form>

      <section className="mj-chat" aria-label="Missed bus help">
        <h2>Missed your bus?</h2>
        <button type="button" className="mj-chip" onClick={() => send("I missed my bus, what now?")}>
          I missed my bus, what now?
        </button>
        <ul>
          {chat.map((m, i) => <li key={i} className={m.from === "me" ? "is-me" : "is-bot"}>{m.text}</li>)}
          {sending && <li className="is-bot mj-muted">Checking the next buses…</li>}
        </ul>
        <div className="mj-send">
          <input value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Ask about your commute"
            onKeyDown={(e) => e.key === "Enter" && send(msg)} aria-label="Message" />
          <button type="button" className="mj-btn" onClick={() => send(msg)} disabled={sending}>Send</button>
        </div>
      </section>
    </main>
  );
}
