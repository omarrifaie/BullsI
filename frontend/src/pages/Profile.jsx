import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getJson } from '../components/api'
import './profile.css'

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

const AUTH_LABELS = {
  citizen: 'US citizen',
  permanent_resident: 'Permanent resident',
  needs_sponsorship: 'Needs visa sponsorship',
}
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Masked for the summary: the full values stay on the server.
const maskEmail = (e) => (e ? e.replace(/^(.)[^@]*/, '$1•••') : '')
const maskPhone = (p) => {
  const digits = (p || '').replace(/\D/g, '')
  return digits.length >= 4 ? `•••-•••-${digits.slice(-4)}` : ''
}
// Hides the street (a first comma part with a number in it), keeps city / state / zip.
const maskAddress = (a) => {
  const parts = (a || '').split(',')
  if (!/\d/.test(parts[0])) return a || ''
  return parts.length > 1 ? `••• ${parts.slice(1).join(',').trim()}` : '•••'
}

function Summary({ profile, onUpdate, onNext }) {
  const school = profile.education?.[0]
  const cities = profile.preferences?.preferred_cities ?? []
  const byDay = DAYS.map((d) => [d, profile.class_schedule.filter((b) => b.day === d)]).filter(([, b]) => b.length)
  const rows = [
    ['Email', maskEmail(profile.email)],
    ['Phone', maskPhone(profile.phone)],
    ['Address', maskAddress(profile.address)],
    ['School', school ? [school.school, school.major].filter(Boolean).join(' · ') : ''],
    ['Work authorization', AUTH_LABELS[profile.work_authorization] || profile.work_authorization],
    ['Preferred cities', cities.join('; ')],
  ]
  return (
    <section className="pf-card" aria-label="Your profile">
      <h2>{profile.name}</h2>
      <dl className="pf-facts">
        {rows.filter(([, v]) => v).map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      {profile.skills.length > 0 && (
        <>
          <h3>Skills</h3>
          <ul className="pf-chips">{profile.skills.map((s) => <li key={s}>{s}</li>)}</ul>
        </>
      )}
      <h3>Class schedule</h3>
      {byDay.length ? (
        <ul className="pf-week">
          {byDay.map(([d, blocks]) => (
            <li key={d}><strong>{d}</strong> {blocks.map((b) => `${b.start}–${b.end}`).join(', ')}</li>
          ))}
        </ul>
      ) : <p className="status">No classes found.</p>}
      <div className="pf-actions">
        <button type="button" className="pf-btn" onClick={onNext}>Go to Internships</button>
        <button type="button" className="pf-btn pf-btn-ghost" onClick={onUpdate}>Update profile</button>
      </div>
    </section>
  )
}

export default function Profile() {
  const navigate = useNavigate()
  const [current, setCurrent] = useState(undefined) // undefined = loading, null = no profile yet
  const [editing, setEditing] = useState(false)

  const [form, setForm] = useState(empty)
  const [resume, setResume] = useState(null)
  const [schedule, setSchedule] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    getJson('/profile/current')
      .then((p) => alive && setCurrent(p))
      .catch((e) => {
        if (!alive) return
        setCurrent(null)
        if (e.status !== 400) setError(`Could not load your profile: ${e.message}`)
      })
    return () => { alive = false }
  }, [])

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
      setCurrent(await getJson('/profile', { method: 'POST', body: data }))
      setEditing(false)
    } catch (err) {
      setError(`Could not create profile: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  if (current === undefined) {
    return <div className="page"><h1>Your profile</h1><p className="status">Loading your profile…</p></div>
  }

  const showForm = !current || editing
  return (
    <div className="page">
      <h1>{current ? 'Your profile' : 'Create your profile'}</h1>
      {!showForm && (
        <Summary profile={current} onUpdate={() => setEditing(true)} onNext={() => navigate('/internships')} />
      )}
      {showForm && (
        <>
          <p>{current ? 'Upload a new resume and schedule to rebuild your profile.' : 'Sign up once. The agents read your resume and class schedule.'}</p>
        <div className="pf-form">
          <label className="pf-field">Name
            <input value={form.name} onChange={set('name')} />
          </label>
          <label className="pf-field">Email
            <input type="email" value={form.email} onChange={set('email')} />
          </label>
          <label className="pf-field">Phone
            <input value={form.phone} onChange={set('phone')} />
          </label>
          <label className="pf-field">Home or dorm address
            <input value={form.address} onChange={set('address')} />
          </label>
          <label className="pf-field">Work authorization
            <select value={form.work_authorization} onChange={set('work_authorization')}>
              <option value="">Choose one</option>
              <option value="citizen">US citizen</option>
              <option value="permanent_resident">Permanent resident</option>
              <option value="needs_sponsorship">Needs visa sponsorship</option>
            </select>
          </label>
          <label className="pf-field">Transportation
            <select value={form.transportation} onChange={set('transportation')}>
              <option value="car">Car</option>
              <option value="transit">Bus</option>
              <option value="bike">Bike</option>
              <option value="walk">Walk</option>
            </select>
          </label>
          <label className="pf-field">Year in school
            <input
              placeholder="e.g. Junior"
              value={form.year_in_school}
              onChange={set('year_in_school')}
            />
          </label>
          <label className="pf-field">Preferred cities (separate with semicolons)
            <input value={form.preferred_cities} onChange={set('preferred_cities')} />
          </label>
          <label className="pf-field">Minimum pay ($/hr)
            <input type="number" value={form.min_pay} onChange={set('min_pay')} />
          </label>
          <label className="pf-field">Max commute (minutes)
            <input
              type="number"
              value={form.max_commute_minutes}
              onChange={set('max_commute_minutes')}
            />
          </label>
          <label className="pf-field">Country (optional)
            <input
              placeholder="United States of America"
              value={form.country}
              onChange={set('country')}
            />
          </label>
          <label className="pf-field">Phone device type (optional)
            <input
              placeholder="e.g. Mobile"
              value={form.phone_device_type}
              onChange={set('phone_device_type')}
            />
          </label>
          <label className="pf-field">How did you hear about us? (optional)
            <input value={form.how_heard} onChange={set('how_heard')} />
          </label>
          <label className="pf-field">Resume (PDF)
            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => setResume(e.target.files[0])}
            />
          </label>
          <label className="pf-field">Class schedule (screenshot)
            <input
              type="file"
              accept="image/*"
              onChange={(e) => setSchedule(e.target.files[0])}
            />
          </label>

          <button type="button" className="pf-btn" onClick={handleSubmit} disabled={loading}>
            {loading ? 'Reading your resume and schedule...' : 'Create profile'}
          </button>
          {error && <p className="pf-error" role="alert">{error}</p>}
        </div>
          {current && (
            <button type="button" className="pf-btn pf-btn-ghost" onClick={() => setEditing(false)}>Cancel</button>
          )}
        </>
      )}
    </div>
  )
}
