import { NavLink } from "react-router-dom";
import logo from "../assets/bullsi-logo.png";

const LINKS = [
  ["/profile", "Profile"],
  ["/internships", "Internships"],
  ["/queue", "Queue"],
  ["/parttime", "Part-time"],
  ["/myjob", "My Job"],
];

export default function Nav() {
  return (
    <header className="nav">
      <nav aria-label="Main">
        {LINKS.map(([to, label]) => (
          <NavLink key={to} to={to} className="nav-link">{label}</NavLink>
        ))}
      </nav>
      <NavLink to="/profile" className="nav-brand">
        <img src={logo} alt="BullsI" width="159" height="36" />
      </NavLink>
    </header>
  );
}
