import { NavLink } from "react-router-dom";

const LINKS = [
  ["/profile", "Profile"],
  ["/internships", "Internships"],
  ["/parttime", "Part-time"],
  ["/myjob", "My Job"],
  ["/queue", "Queue"],
];

export default function Nav() {
  return (
    <header className="nav">
      <NavLink to="/profile" className="nav-brand">BullPen</NavLink>
      <nav aria-label="Main">
        {LINKS.map(([to, label]) => (
          <NavLink key={to} to={to} className="nav-link">{label}</NavLink>
        ))}
      </nav>
    </header>
  );
}
