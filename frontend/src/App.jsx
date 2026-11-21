import { Link, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Profile from "./pages/Profile";
import Internships from "./pages/Internships";
import PartTime from "./pages/PartTime";
import MyJob from "./pages/MyJob";
import Queue from "./pages/Queue";
import MockWorkday from "./pages/MockWorkday";

function NotFound() {
  return (
    <div className="page">
      <h1>Page not found</h1>
      <p>That page doesn’t exist. <Link to="/profile">Go to your profile</Link>.</p>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/profile" replace />} />
        <Route path="profile" element={<Profile />} />
        <Route path="internships" element={<Internships />} />
        <Route path="parttime" element={<PartTime />} />
        <Route path="myjob" element={<MyJob />} />
        <Route path="queue" element={<Queue />} />
        <Route path="*" element={<NotFound />} />
      </Route>
      {/* Outside Layout: a stand-in employer portal, so no BullPen nav. */}
      <Route path="mock-workday/:jobId" element={<MockWorkday />} />
    </Routes>
  );
}
