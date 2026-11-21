import { useEffect, useState } from "react";

// What the agents are doing during a slow call: steps tick over every `everyMs`, the last one stays active.
export default function AgentSteps({ steps, everyMs = 3000 }) {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setStep((s) => Math.min(s + 1, steps.length - 1)), everyMs);
    return () => clearInterval(t);
  }, [steps.length, everyMs]);
  return (
    <ol className="agent-steps" aria-live="polite">
      {steps.map((text, i) => (
        <li key={text} className={i < step ? "done" : i === step ? "active" : ""}>{text}</li>
      ))}
    </ol>
  );
}
