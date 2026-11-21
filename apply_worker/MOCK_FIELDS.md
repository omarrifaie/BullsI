# Mock Workday fields

Generated from `workday_fields.json` by `python make_mock_fields.py`. Don't edit by hand.

The React `/mock-workday/:jobId` page must use these exact `data-automation-id` values, the same page order
(Posting -> Apply modal -> optional Sign in -> My Information -> My Experience -> Review), and the same widget
behavior as `apply_worker/mock/workday_mock.html`:

- **text / textarea**: a plain `<input type=text>` / `<textarea>` with the id on the input.
- **dropdown**: a `<button>` with the id that shows `Select One`. Clicking it opens the next sibling
  `<ul role=listbox>` with `<li role=option>` items. Picking one sets the button text to the option text.
- **checkbox**: an `<input type=checkbox>` with the id.
- **date**: a wrapper with the id containing two inputs: `dateSectionMonth-input` (MM) and
  `dateSectionYear-input` (YYYY).
- **file**: one `<input type=file multiple>`. The worker uploads the resume and cover letter PDFs together.
- Required fields have `aria-required="true"`.
- The current step in the progress bar has `data-automation-id="progressBarActiveStep"` and its text is the
  page name. The footer button `bottom-navigation-next-button` reads `Save and Continue` on pages 1-2 and
  `Submit` on Review. The worker never clicks it on page 2 or later.
- Work experience and education rows are added with the `add-button` inside each section. Each row is wrapped
  in `workExperience-N` / `education-N` (N starts at 1).

Status: **provisional** = a standard Workday id, to be checked on a live posting in W3. **mock only** = real
Workday generates these per company (the worker matches them by question text).

## Fields the worker fills

| data-automation-id | Field | Input type | Page | Section | Required | Status |
|---|---|---|---|---|---|---|
| `sourcePrompt` | How Did You Hear About Us? | dropdown | 1. My Information |  | yes | provisional |
| `countryDropdown` | Country | dropdown | 1. My Information |  | yes | provisional |
| `legalNameSection_firstName` | First Name | text | 1. My Information |  | yes | provisional |
| `legalNameSection_lastName` | Last Name | text | 1. My Information |  | yes | provisional |
| `addressSection_addressLine1` | Address Line 1 | text | 1. My Information |  | yes | provisional |
| `addressSection_city` | City | text | 1. My Information |  | yes | provisional |
| `addressSection_countryRegion` | State | dropdown | 1. My Information |  | yes | provisional |
| `addressSection_postalCode` | Postal Code | text | 1. My Information |  | yes | provisional |
| `email` | Email Address | text | 1. My Information |  | yes | provisional |
| `phone-device-type` | Phone Device Type | dropdown | 1. My Information |  | yes | provisional |
| `phone-number` | Phone Number | text | 1. My Information |  | yes | provisional |
| `workAuthorizationQuestion` | Are you legally authorized to work in the United States? | dropdown | 1. My Information |  | yes | mock only |
| `sponsorshipQuestion` | Will you now or in the future require sponsorship? | dropdown | 1. My Information |  | yes | mock only |
| `jobTitle` | Job Title | text | 2. My Experience | workExperienceSection > workExperience-N | yes | provisional |
| `company` | Company | text | 2. My Experience | workExperienceSection > workExperience-N | yes | provisional |
| `location` | Location | text | 2. My Experience | workExperienceSection > workExperience-N | no | provisional |
| `currentlyWorkHere` | I currently work here | checkbox | 2. My Experience | workExperienceSection > workExperience-N | no | provisional |
| `formField-startDate` | From | date | 2. My Experience | workExperienceSection > workExperience-N | yes | provisional |
| `formField-endDate` | To | date | 2. My Experience | workExperienceSection > workExperience-N | no | provisional |
| `description` | Role Description | textarea | 2. My Experience | workExperienceSection > workExperience-N | no | provisional |
| `school` | School or University | text | 2. My Experience | educationSection > education-N | yes | provisional |
| `degree` | Degree | dropdown | 2. My Experience | educationSection > education-N | yes | provisional |
| `fieldOfStudy` | Field of Study | text | 2. My Experience | educationSection > education-N | no | provisional |
| `gpa` | Overall Result (GPA) | text | 2. My Experience | educationSection > education-N | no | provisional |
| `formField-lastYearAttended` | To (Actual or Expected) | date | 2. My Experience | educationSection > education-N | no | provisional |
| `file-upload-input-ref` | Resume/CV and Cover Letter | file | 2. My Experience |  | yes | provisional |

## Voluntary disclosures (never filled, inside `voluntaryDisclosuresSection`)

| data-automation-id | Field | Input type | Page | Status |
|---|---|---|---|---|
| `gender` | Gender | dropdown | 2. My Experience | mock only |
| `ethnicityDropdown` | Race/Ethnicity | dropdown | 2. My Experience | mock only |
| `hispanicOrLatino` | Are you Hispanic or Latino? | dropdown | 2. My Experience | mock only |
| `veteranStatus` | Veteran Status | dropdown | 2. My Experience | mock only |
| `disabilityStatus` | I have a disability (or previously had a disability) | checkbox | 2. My Experience | mock only |

## Buttons

| data-automation-id | Text | Status |
|---|---|---|
| `adventureButton` | Apply | provisional |
| `applyManually` | Apply Manually | provisional |
| `autofillWithResume` | Autofill with Resume | provisional |
| `bottom-navigation-next-button` | Save and Continue | provisional |
| `add-button` | Add | provisional |

## Other ids

| data-automation-id | Purpose | Page |
|---|---|---|
| `progressBarActiveStep` | see widget rules above | All |
| `dateSectionMonth-input` | see widget rules above | All |
| `dateSectionYear-input` | see widget rules above | All |
| `workExperienceSection` | section wrapper, rows are `workExperience-N` | 2. My Experience |
| `educationSection` | section wrapper, rows are `education-N` | 2. My Experience |
| `jobPostingHeader` | Job title on the posting page | Posting |
| `signInContent` | Sign-in page wrapper (worker waits for the student here) | Sign in |
| `signInEmail` | Sign-in email (worker never types here) | Sign in |
| `password` | Sign-in password (worker never types here) | Sign in |
| `signInSubmitButton` | Sign In button (student clicks it) | Sign in |
| `createAccountLink` | Create Account link | Sign in |
| `progressBarInactiveStep` | Progress steps that are not current | All |
