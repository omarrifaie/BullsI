"""Stub data for teammate-owned routes and the test profile."""
from typing import Any

FAKE_PROFILE: dict[str, Any] = {
  "name": "Alex Rivera",
  "email": "alexrivera@usf.edu",
  "phone": "(813) 555-0142",
  "address": "4202 E Fowler Ave, Tampa, FL 33620",
  "work_authorization": "citizen",
  "education": [{
    "school": "University of South Florida",
    "degree": "B.S.",
    "major": "Computer Science",
    "gpa": "3.7",
    "graduation": "May 2028",
    "year_in_school": "sophomore",
  }],
  "experience": [{
    "id": "exp1",
    "title": "IT Help Desk Assistant",
    "organization": "USF Information Technology",
    "location": "Tampa, FL",
    "start": "Aug 2025",
    "end": "Present",
    "bullets": [
      {"id": "exp1_b1", "text": "Resolved 40+ weekly student tickets for Wi-Fi, Canvas, and account access issues"},
      {"id": "exp1_b2", "text": "Wrote a Python script that auto-tags tickets, cutting triage time by 30%"},
    ],
  }],
  "projects": [{
    "id": "proj1",
    "name": "Bull Runner Tracker",
    "tech": ["React", "FastAPI", "PostgreSQL"],
    "bullets": [
      {"id": "proj1_b1", "text": "Built a live map of campus shuttle positions used by 300+ students"},
      {"id": "proj1_b2", "text": "Designed a REST API that polls GPS feeds every 10 seconds"},
    ],
  }],
  "skills": ["Python", "JavaScript", "React", "FastAPI", "SQL", "Git", "customer service"],
  "class_schedule": [
    {"day": "Mon", "start": "09:30", "end": "10:45"},
    {"day": "Wed", "start": "09:30", "end": "10:45"},
    {"day": "Tue", "start": "11:00", "end": "12:15"},
    {"day": "Thu", "start": "11:00", "end": "12:15"},
  ],
  "transportation": "transit",
  "preferences": {
    "roles": ["software engineering", "data science"],
    "preferred_cities": ["Tampa, FL"],
    "min_pay": 14.0,
    "max_commute_minutes": 30,
  },
}

FAKE_COMMUTE: dict[str, Any] = {
  "minutes": 24,
  "car_free": True,
  "transfers": 1,
  "co2_saved_kg_week": 3.2,
  "steps": [
    {"mode": "WALK", "line": "", "from_stop": "Home", "to_stop": "Marshall Student Center",
     "depart": "14:18", "arrive": "14:22", "polyline": ""},
    {"mode": "TRANSIT", "line": "Bull Runner C", "from_stop": "Marshall Student Center",
     "to_stop": "USF Health", "depart": "14:22", "arrive": "14:35", "polyline": ""},
    {"mode": "TRANSIT", "line": "HART 6", "from_stop": "Fletcher Ave @ 30th St",
     "to_stop": "Fowler Ave @ 56th St", "depart": "14:38", "arrive": "14:42", "polyline": ""},
  ],
}


def _parttime(job_id: str, title: str, company: str, address: str, lat: float, lng: float,
              shifts: list[dict[str, str]], pay: float, skills: list[str], score: int,
              reason: str) -> dict[str, Any]:
  return {
    "id": job_id, "mode": "parttime", "title": title, "company": company, "address": address,
    "lat": lat, "lng": lng, "apply_url": f"http://localhost:5173/mock-workday/{job_id}",
    "shifts": shifts, "pay": pay, "skills": skills,
    "match": {"score": score, "reason": reason}, "commute": FAKE_COMMUTE,
  }


FAKE_PARTTIME: list[dict[str, Any]] = [
  _parttime("job_pt000001", "Barista", "Bulls Brew Cafe", "5010 E Fowler Ave, Tampa, FL 33617", 28.0545, -82.4008,
            [{"day": "Tue", "start": "15:00", "end": "21:00"}, {"day": "Thu", "start": "15:00", "end": "21:00"}],
            15.0, ["customer service", "cash handling"], 88, "Fits your Tue/Thu afternoons, 24 min by bus"),
  _parttime("job_pt000002", "Library Desk Assistant", "Tampa-Hillsborough Public Library",
            "2902 W Bearss Ave, Tampa, FL 33618", 28.0880, -82.4960,
            [{"day": "Mon", "start": "13:00", "end": "18:00"}, {"day": "Wed", "start": "13:00", "end": "18:00"}],
            14.5, ["organization", "customer service"], 79, "Mon/Wed afternoons free after class"),
  _parttime("job_pt000003", "Retail Sales Associate", "Target", "1 Tampa Palms Blvd, Tampa, FL 33647", 28.1290, -82.3720,
            [{"day": "Fri", "start": "16:00", "end": "22:00"}, {"day": "Sat", "start": "10:00", "end": "16:00"}],
            16.0, ["customer service", "inventory"], 72, "Weekend shifts avoid all your classes"),
  _parttime("job_pt000004", "IT Support Technician", "Moffitt Cancer Center", "12902 USF Magnolia Dr, Tampa, FL 33612",
            28.0640, -82.4210, [{"day": "Fri", "start": "08:00", "end": "14:00"}],
            18.0, ["troubleshooting", "Windows", "customer service"], 84, "On-campus IT role matching your help desk work"),
  _parttime("job_pt000005", "Math Tutor", "Club Z! Tutoring", "Remote / Tampa, FL", 28.0587, -82.4139,
            [{"day": "Sun", "start": "12:00", "end": "17:00"}],
            20.0, ["tutoring", "math", "communication"], 81, "Top pay and Sunday hours never clash"),
]

