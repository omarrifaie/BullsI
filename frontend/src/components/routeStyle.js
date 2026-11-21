// Route drawing helpers shared by the route panel and the map. Pure functions, no React.

// HART reports the same color for every line, so lines get colors from this palette in the order they appear
// (Okabe-Ito colors: distinguishable with common color blindness).
const PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"];
export const WALK_COLOR = "#5B6B63";

export function lineColors(steps = []) {
  const colors = new Map();
  for (const s of steps) {
    if (s.mode === "TRANSIT" && !colors.has(s.line)) colors.set(s.line, PALETTE[colors.size % PALETTE.length]);
  }
  return colors;
}

export const usesTransit = (steps = []) => steps.some((s) => s.mode === "TRANSIT");

// Google returns one step per turn while walking; show them as one "Walk N min" line.
export function groupSteps(steps = []) {
  const out = [];
  for (const s of steps) {
    const last = out[out.length - 1];
    if (s.mode !== "TRANSIT" && last?.mode === "WALK") last.minutes += s.minutes ?? 0;
    else out.push(s.mode === "TRANSIT" ? s : { mode: "WALK", minutes: s.minutes ?? 0 });
  }
  return out;
}

export function costLabel(commute) {
  if (commute.cost_usd == null) return commute.cost_note || "Fare not known";
  if (commute.cost_usd === 0) return commute.cost_note;
  return `$${commute.cost_usd.toFixed(2)} each way (${commute.cost_note})`;
}
