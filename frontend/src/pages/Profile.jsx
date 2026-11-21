import { useState } from 'react'
import { Link } from 'react-router-dom'
import { getJson } from '../components/api'

const empty = {
  name: '',
  email: '',
  phone: '',
  address: '',
  work_authorization: '',
  transportation: 'transit',
  year_in_school: '',
  preferred_cities: 'Tampa, FL',
  min_pay: '',
  max_commute_minutes: '',
  country: '',
  phone_device_type: '',
  how_heard: '',
}

const field = { display: 'flex', flexDirection: 'column', gap: 4 }

export default function Profile() {
  const [form, setForm] = useState(empty)
  const [resume, setResume] = useState(null)
  const [schedule, setSchedule] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  async function handleSubmit() {
    if (!resume || !schedule) {
      setError('Please upload both your resume PDF and your schedule screenshot.')
      return
    }
    setError('')
    setLoading(true)
    try {
      const data = new FormData()
      Object.entries(form).forEach(([k, v]) => {
        if (v !== '') data.append(k, v)
      })
      data.append('resume', resume)
      data.append('schedule', schedule)
      setResult(await getJson('/profile', { method: 'POST', body: data }))
    } catch (err) {
      setError(`Could not create profile: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 560, margin: '0 auto', padding: 16, textAlign: 'left' }}>
      <h1>Create your profile</h1>
      <p>Sign up once. The agents read your resume and class schedule.</p>

      <div style={{ display: 'grid', gap: 12 }}>
        <label style={field}>Name
          <input value={form.name} onChange={set('name')} />
        </label>
        <label style={field}>Email
          <input type="email" value={form.email} onChange={set('email')} />
        </label>
        <label style={field}>Phone
          <input value={form.phone} onChange={set('phone')} />
        </label>
        <label style={field}>Home or dorm address
          <input value={form.address} onChange={set('address')} />
        </label>
        <label style={field}>Work authorization
          <select value={form.work_authorization} onChange={set('work_authorization')}>
            <option value="">Choose one</option>
            <option value="citizen">US citizen</option>
            <option value="permanent_resident">Permanent resident</option>
            <option value="needs_sponsorship">Needs visa sponsorship</option>
          </select>
        </label>
        <label style={field}>Transportation
          <select value={form.transportation} onChange={set('transportation')}>
            <option value="car">Car</option>
            <option value="transit">Bus</option>
            <option value="bike">Bike</option>
            <option value="walk">Walk</option>
          </select>
        </label>
        <label style={field}>Year in school
          <input
            placeholder="e.g. Junior"
            value={form.year_in_school}
            onChange={set('year_in_school')}
          />
        </label>
        <label style={field}>Preferred cities (separate with semicolons)
          <input value={form.preferred_cities} onChange={set('preferred_cities')} />
        </label>
        <label style={field}>Minimum pay ($/hr)
          <input type="number" value={form.min_pay} onChange={set('min_pay')} />
        </label>
        <label style={field}>Max commute (minutes)
          <input
            type="number"
            value={form.max_commute_minutes}
            onChange={set('max_commute_minutes')}
          />
        </label>
        <label style={field}>Country (optional)
          <input
            placeholder="United States of America"
            value={form.country}
            onChange={set('country')}
          />
        </label>
        <label style={field}>Phone device type (optional)
          <input
            placeholder="e.g. Mobile"
            value={form.phone_device_type}
            onChange={set('phone_device_type')}
          />
        </label>
        <label style={field}>How did you hear about us? (optional)
          <input value={form.how_heard} onChange={set('how_heard')} />
        </label>
        <label style={field}>Resume (PDF)
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setResume(e.target.files[0])}
          />
        </label>
        <label style={field}>Class schedule (screenshot)
          <input
            type="file"
            accept="image/*"
            onChange={(e) => setSchedule(e.target.files[0])}
          />
        </label>

        <button onClick={handleSubmit} disabled={loading}>
          {loading ? 'Reading your resume and schedule...' : 'Create profile'}
        </button>
        {error && <p style={{ color: 'crimson' }}>{error}</p>}
      </div>

      {result && (
        <div style={{ marginTop: 24 }}>
          <h2>Profile created</h2>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>
            {JSON.stringify(result, null, 2)}
          </pre>
          <Link to="/internships">Go to Internships</Link>
        </div>
      )}
    </div>
  )
}
