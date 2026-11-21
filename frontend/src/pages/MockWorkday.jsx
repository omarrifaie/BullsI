import { createContext, useContext, useEffect, useId, useLayoutEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { getJson } from "../components/api";
import "./mockworkday.css";

/*
  React port of apply_worker/mock/workday_mock.html (spec: apply_worker/MOCK_FIELDS.md). Same data-automation-ids,
  element ids, labels, page order and widget behavior, so the apply worker's tests run against either page.
  Every step stays in the DOM and is shown/hidden with CSS, like the HTML mock. Inputs are uncontrolled so the
  worker's fill() and the page never fight over values. Query params: ?signin=1, ?title=, ?company=.
  Test hooks: window.__clicks, window.__submitClicks, <body data-submit-clicks>. Never calls the backend on Submit.
*/

const STEPS = [["my_information", "My Information"], ["my_experience", "My Experience"], ["review", "Review"]];
const STEP_IDS = STEPS.map(([id]) => id);

// Which dropdown is open (one at a time, like Workday). Escape or a click elsewhere closes it.
const OpenContext = createContext(null);

function Dropdown({ id, automationId, required, options }) {
  const { open, setOpen } = useContext(OpenContext);
  const key = useId();
  const [value, setValue] = useState(null);
  const isOpen = open === key;
  return (
    <>
      <button className="dropdown" type="button" id={id} data-automation-id={automationId}
        aria-required={required ? "true" : undefined} aria-haspopup="listbox"
        onClick={() => setOpen(isOpen ? null : key)}>
        {value ?? "Select One"}
      </button>
      <ul role="listbox" className={isOpen ? "open" : undefined}>
        {options.map((o) => (
          <li role="option" key={o} onClick={() => { setValue(o); setOpen(null); }}>{o}</li>
        ))}
      </ul>
    </>
  );
}

function Req() {
  return <span className="req">*</span>;
}

function DateField({ automationId, label, required }) {
  return (
    <div className="formField date" data-automation-id={automationId}>
      <label>{label}{required && <> <Req /></>}</label>
      <input type="text" placeholder="MM" data-automation-id="dateSectionMonth-input" aria-required={required ? "true" : undefined} />
      <input type="text" placeholder="YYYY" data-automation-id="dateSectionYear-input" aria-required={required ? "true" : undefined} />
    </div>
  );
}

function WorkRow({ n }) {
  return (
    <div data-automation-id={`workExperience-${n}`}>
      <fieldset>
        <legend>Work Experience <span className="n">{n}</span></legend>
        <div className="formField"><label>Job Title <Req /></label>
          <input type="text" data-automation-id="jobTitle" aria-required="true" /></div>
        <div className="formField"><label>Company <Req /></label>
          <input type="text" data-automation-id="company" aria-required="true" /></div>
        <div className="formField"><label>Location</label>
          <input type="text" data-automation-id="location" /></div>
        <div className="formField"><label><input type="checkbox" data-automation-id="currentlyWorkHere" /> I currently work here</label></div>
        <DateField automationId="formField-startDate" label="From" required />
        <DateField automationId="formField-endDate" label="To" />
        <div className="formField"><label>Role Description</label>
          <textarea rows="3" data-automation-id="description" /></div>
      </fieldset>
    </div>
  );
}

function EducationRow({ n }) {
  return (
    <div data-automation-id={`education-${n}`}>
      <fieldset>
        <legend>Education <span className="n">{n}</span></legend>
        <div className="formField"><label>School or University <Req /></label>
          <input type="text" data-automation-id="school" aria-required="true" /></div>
        <div className="formField"><label>Degree <Req /></label>
          <Dropdown automationId="degree" required
            options={["High School Diploma", "Associate's Degree", "Bachelor's Degree", "Master's Degree", "Doctorate"]} />
        </div>
        <div className="formField"><label>Field of Study</label>
          <input type="text" data-automation-id="fieldOfStudy" /></div>
        <div className="formField"><label>Overall Result (GPA)</label>
          <input type="text" data-automation-id="gpa" /></div>
        <DateField automationId="formField-lastYearAttended" label="To (Actual or Expected)" />
      </fieldset>
    </div>
  );
}

function TextField({ id, automationId, label }) {
  return (
    <div className="formField"><label htmlFor={id}>{label} <Req /></label>
      <input type="text" id={id} data-automation-id={automationId} aria-required="true" /></div>
  );
}

function DropdownField({ id, automationId, label, required = true, options }) {
  return (
    <div className="formField">
      <label htmlFor={id}>{label}{required && <> <Req /></>}</label>
      <Dropdown id={id} automationId={automationId} required={required} options={options} />
    </div>
  );
}

// Title/company: ?title/?company, else the queued or ranked job with this id, else a demo posting.
function usePosting(jobId, params) {
  const [posting, setPosting] = useState({ title: "Software Engineering Intern", company: "Demo Company" });
  useEffect(() => {
    if (params.get("title") || params.get("company")) return;
    let alive = true;
    (async () => {
      try {
        const queued = (await getJson("/queue")).find((q) => q.job_id === jobId);
        const job = queued ?? (await getJson("/jobs?mode=internship")).find((j) => j.id === jobId);
        if (alive && job) setPosting({ title: job.title, company: job.company });
      } catch {
        // No backend or no profile: keep the demo posting.
      }
    })();
    return () => { alive = false; };
  }, [jobId, params]);
  return {
    title: params.get("title") || posting.title,
    company: params.get("company") || posting.company,
  };
}

export default function MockWorkday() {
  const { jobId } = useParams();
  const [params] = useSearchParams();
  const { title, company } = usePosting(jobId, params);
  const [current, setCurrent] = useState("posting");
  const [modalOpen, setModalOpen] = useState(false);
  const [open, setOpen] = useState(null);
  const [rows, setRows] = useState({ work: 0, education: 0 });
  const [submitted, setSubmitted] = useState(false);

  // Native listeners, installed before paint: they record clicks on every button, including ones the worker
  // injects (its sign-in banner's Continue), and close an open listbox on Escape or a click outside a dropdown.
  useLayoutEffect(() => {
    window.__clicks = [];
    window.__submitClicks = 0;
    document.body.dataset.submitClicks = "0";
    const onClick = (e) => {
      const btn = e.target.closest("button");
      if (btn) window.__clicks.push(btn.textContent.trim());
      if (!e.target.closest("button.dropdown, li[role=option]")) setOpen(null);
    };
    const onKey = (e) => { if (e.key === "Escape") setOpen(null); };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
      delete document.body.dataset.submitClicks;
    };
  }, []);

  const start = () => setCurrent(params.get("signin") === "1" ? "signin" : "my_information");
  const next = () => {
    if (current === "review") {
      window.__submitClicks += 1;
      document.body.dataset.submitClicks = String(window.__submitClicks);
      setSubmitted(true);
      return;
    }
    setCurrent(STEP_IDS[STEP_IDS.indexOf(current) + 1]);
  };
  const show = (name) => `step${current === name ? " active" : ""}`;
  const add = (kind) => setRows((r) => ({ ...r, [kind]: r[kind] + 1 }));

  return (
    <OpenContext.Provider value={{ open, setOpen }}>
      <div className="mw-root">
        <header className="mw-header">
          <strong>{company}</strong>
          <span>Careers</span>
        </header>
        <main className="mw-main">
          <ol className="progress">
            {STEPS.map(([id, label]) => (
              <li key={id} data-step={id}
                data-automation-id={current === "posting" || current === "signin" ? undefined
                  : current === id ? "progressBarActiveStep" : "progressBarInactiveStep"}>
                {label}
              </li>
            ))}
          </ol>

          {/* Posting */}
          <section className={show("posting")} id="page-posting">
            <h2 data-automation-id="jobPostingHeader" id="job-title">{title}</h2>
            <p id="job-company">{company}</p>
            <button data-automation-id="adventureButton" type="button" onClick={() => setModalOpen(true)}>Apply</button>
            <div className={`modal${modalOpen ? " open" : ""}`} id="apply-modal">
              <p>Start Your Application</p>
              <button data-automation-id="autofillWithResume" type="button" onClick={start}>Autofill with Resume</button>
              <button data-automation-id="applyManually" type="button" onClick={start}>Apply Manually</button>
            </div>
          </section>

          {/* Sign in (only with ?signin=1) */}
          <section className={show("signin")} id="page-signin">
            <div data-automation-id="signInContent">
              <h2>Sign In</h2>
              <div className="formField"><label htmlFor="si-email">Email Address</label>
                <input type="email" id="si-email" data-automation-id="signInEmail" /></div>
              <div className="formField"><label htmlFor="si-password">Password</label>
                <input type="password" id="si-password" data-automation-id="password" /></div>
              <button data-automation-id="signInSubmitButton" type="button" onClick={() => setCurrent("my_information")}>Sign In</button>
              <a href="#" data-automation-id="createAccountLink" onClick={(e) => e.preventDefault()}>Create Account</a>
            </div>
          </section>

          {/* Page 1: My Information */}
          <section className={show("my_information")} id="page-my_information">
            <h2>My Information</h2>
            <DropdownField id="f-source" automationId="sourcePrompt" label="How Did You Hear About Us?"
              options={["Job Board", "LinkedIn", "Career Fair", "Referral", "Company Website"]} />
            <DropdownField id="f-country" automationId="countryDropdown" label="Country"
              options={["United States of America", "Canada", "Mexico"]} />
            <TextField id="f-first" automationId="legalNameSection_firstName" label="First Name" />
            <TextField id="f-last" automationId="legalNameSection_lastName" label="Last Name" />
            <TextField id="f-addr" automationId="addressSection_addressLine1" label="Address Line 1" />
            <TextField id="f-city" automationId="addressSection_city" label="City" />
            <DropdownField id="f-state" automationId="addressSection_countryRegion" label="State"
              options={["Alabama", "California", "Florida", "Georgia", "New York", "Texas"]} />
            <TextField id="f-zip" automationId="addressSection_postalCode" label="Postal Code" />
            <TextField id="f-email" automationId="email" label="Email Address" />
            <DropdownField id="f-phonetype" automationId="phone-device-type" label="Phone Device Type"
              options={["Mobile", "Home", "Work"]} />
            <TextField id="f-phone" automationId="phone-number" label="Phone Number" />
            <DropdownField id="f-auth" automationId="workAuthorizationQuestion"
              label="Are you legally authorized to work in the United States?" options={["Yes", "No"]} />
            <DropdownField id="f-spons" automationId="sponsorshipQuestion"
              label="Will you now or in the future require sponsorship?" options={["Yes", "No"]} />
          </section>

          {/* Page 2: My Experience */}
          <section className={show("my_experience")} id="page-my_experience">
            <h2>My Experience</h2>
            <div data-automation-id="workExperienceSection">
              <h3>Work Experience</h3>
              <div className="entries">
                {Array.from({ length: rows.work }, (_, i) => <WorkRow key={i} n={i + 1} />)}
              </div>
              <button data-automation-id="add-button" type="button" onClick={() => add("work")}>Add</button>
            </div>
            <div data-automation-id="educationSection">
              <h3>Education</h3>
              <div className="entries">
                {Array.from({ length: rows.education }, (_, i) => <EducationRow key={i} n={i + 1} />)}
              </div>
              <button data-automation-id="add-button" type="button" onClick={() => add("education")}>Add</button>
            </div>
            <div className="formField">
              <label htmlFor="f-files">Resume/CV and Cover Letter <Req /></label>
              <input type="file" id="f-files" multiple accept=".pdf" data-automation-id="file-upload-input-ref" aria-required="true" />
            </div>
            <fieldset data-automation-id="voluntaryDisclosuresSection">
              <legend>Voluntary Disclosures</legend>
              <DropdownField id="v-gender" automationId="gender" label="Gender" required={false}
                options={["Female", "Male", "I do not wish to answer"]} />
              <DropdownField id="v-eth" automationId="ethnicityDropdown" label="Race/Ethnicity" required={false}
                options={["Asian", "Black or African American", "White", "Two or More Races", "I do not wish to answer"]} />
              <DropdownField id="v-hisp" automationId="hispanicOrLatino" label="Are you Hispanic or Latino?" required={false}
                options={["Yes", "No", "I do not wish to answer"]} />
              <DropdownField id="v-vet" automationId="veteranStatus" label="Veteran Status" required={false}
                options={["I am not a protected veteran", "I identify as a protected veteran", "I do not wish to answer"]} />
              <div className="formField">
                <label><input type="checkbox" data-automation-id="disabilityStatus" /> I have a disability (or previously had a disability)</label>
              </div>
            </fieldset>
          </section>

          {/* Page 3: Review */}
          <section className={show("review")} id="page-review">
            <h2>Review</h2>
            <p>Review your application, then click Submit.</p>
            <p id="submitted" className="mw-submitted" hidden={!submitted}>
              Submitted (mock). This practice page doesn’t send anything anywhere.
            </p>
          </section>
        </main>

        <footer className={`mw-footer${STEP_IDS.includes(current) ? "" : " hidden"}`} id="footer">
          <button data-automation-id="bottom-navigation-next-button" type="button" id="next" onClick={next}>
            {current === "review" ? "Submit" : "Save and Continue"}
          </button>
        </footer>
      </div>
    </OpenContext.Provider>
  );
}
