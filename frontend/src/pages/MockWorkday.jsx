import { useParams } from 'react-router-dom'

export default function MockWorkday() {
  const { jobId } = useParams()
  return <h1>Mock Workday: {jobId}</h1>
}
