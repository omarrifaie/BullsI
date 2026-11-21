import { useState } from "react";

// Hiring platforms: an apply URL on one of these says nothing about the company's own domain.
const ATS_HOSTS = [
  "myworkdayjobs.com", "myworkdaysite.com", "workday.com", "ultipro.com", "ultipro.ca", "ukg.net", "greenhouse.io",
  "lever.co", "ashbyhq.com", "icims.com", "oraclecloud.com", "taleo.net", "bamboohr.com", "workable.com",
  "smartrecruiters.com", "jibeapply.com", "avature.net", "eightfold.ai", "rippling.com", "yello.co", "jobvite.com",
  "successfactors.com", "successfactors.eu", "applytojob.com", "breezy.hr", "recruitee.com", "paylocity.com",
  "adp.com", "paycomonline.net", "dayforcehcm.com", "brassring.com", "phenompeople.com", "simplify.jobs",
  "linkedin.com", "indeed.com", "joinhandshake.com", "wellfound.com", "glassdoor.com", "teamtailor.com",
  "pinpointhq.com", "dover.com", "jazzhr.com", "zohorecruit.com", "gem.com", "careers-page.com", "hire.trakstar.com",
];
const NAME_NOISE = /\b(inc|llc|ltd|corp|corporation|co|company|group|holdings|plc|lp|llp|the)\b\.?/g;

function registrable(host) {
  const parts = host.split(".");
  const n = /^(co|com|org|net|ac|gov)\.[a-z]{2}$/.test(parts.slice(-2).join(".")) ? 3 : 2;
  return parts.slice(-n).join(".");
}

// The company's own domain: the apply URL's host when it isn't a hiring platform, else a <name>.com guess.
export function companyDomain(applyUrl, company) {
  try {
    const host = new URL(applyUrl).hostname.toLowerCase();
    if (!ATS_HOSTS.some((ats) => host === ats || host.endsWith(`.${ats}`))) return registrable(host);
  } catch { /* not a URL: fall through to the name guess */ }
  const slug = (company || "").toLowerCase().replace(/&/g, "and").replace(NAME_NOISE, "").replace(/[^a-z0-9]/g, "");
  return slug.length >= 2 && slug.length <= 30 ? `${slug}.com` : null;
}

function initials(company) {
  const words = (company || "?").replace(/[^A-Za-z0-9 ]/g, " ").trim().split(/\s+/);
  return (words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)).toUpperCase();
}

// Stable per-name hue; 32% lightness keeps white initials above 4.5:1.
function nameColor(company) {
  let h = 0;
  for (const ch of company || "") h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h} 45% 32%)`;
}

// Google's favicon for the company's domain. Initials show until a real icon has loaded, and stay if there's none.
export default function CompanyLogo({ applyUrl, company }) {
  const domain = companyDomain(applyUrl, company);
  const [loaded, setLoaded] = useState(false);
  return (
    <>
      {!loaded && <span className="in-logo in-logo-initials" style={{ background: nameColor(company) }} aria-hidden="true">{initials(company)}</span>}
      {domain && (
        <img
          className="in-logo"
          style={loaded ? undefined : { display: "none" }} // still loads while hidden
          src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=128`}
          alt=""
          draggable="false"
          onLoad={(e) => setLoaded(e.currentTarget.naturalWidth > 16)} // Google's "no icon" globe is 16px
        />
      )}
    </>
  );
}
