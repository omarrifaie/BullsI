import { useParams } from "react-router-dom";
import { BackendStatus } from "../components/Layout";

export default function MockWorkday() {
  const { jobId } = useParams();
  return (
    <div className="page">
      <h1>Mock Workday</h1>
      <p>A practice Workday application for job {jobId}, filled in by the apply worker.</p>
      <BackendStatus />
    </div>
  );
}
