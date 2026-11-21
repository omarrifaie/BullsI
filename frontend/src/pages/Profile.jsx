import { BackendStatus } from "../components/Layout";

export default function Profile() {
  return (
    <div className="page">
      <h1>Profile</h1>
      <p>Upload your resume and class schedule so BullPen can match jobs to you.</p>
      <BackendStatus />
    </div>
  );
}
