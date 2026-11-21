import { Routes, Route, NavLink } from 'react-router-dom'
import Profile from './pages/Profile'
import Internships from './pages/Internships'
import PartTime from './pages/PartTime'
import Queue from './pages/Queue'
import MyJob from './pages/MyJob'
import MockWorkday from './pages/MockWorkday'

export default function App() {
  return (
    <>
      <nav style={{ display: 'flex', gap: 16, padding: 16 }}>
        <NavLink to="/">Profile</NavLink>
        <NavLink to="/internships">Internships</NavLink>
        <NavLink to="/part-time">Part-time</NavLink>
        <NavLink to="/queue">Queue</NavLink>
        <NavLink to="/my-job">My Job</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<Profile />} />
        <Route path="/internships" element={<Internships />} />
        <Route path="/part-time" element={<PartTime />} />
        <Route path="/queue" element={<Queue />} />
        <Route path="/my-job" element={<MyJob />} />
        <Route path="/mock-workday/:jobId" element={<MockWorkday />} />
      </Routes>
    </>
  )
}
