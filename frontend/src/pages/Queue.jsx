import { BackendStatus } from "../components/Layout";

export default function Queue() {
  return (
    <div className="page">
      <h1>Application queue</h1>
      <p>Queued internships with tailored resumes and cover letters, ready to apply.</p>
      <BackendStatus />
    </div>
  );
}
