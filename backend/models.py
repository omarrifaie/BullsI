"""Pydantic models for the shared contract (job object, commute, profile)."""
from typing import Literal, Optional

from pydantic import BaseModel


class TimeBlock(BaseModel):
  day: str  # "Mon".."Sun"
  start: str  # "HH:MM" 24h
  end: str


class Match(BaseModel):
  score: int
  reason: str


class CommuteStep(BaseModel):
  mode: Literal["WALK", "TRANSIT"]
  line: str = ""
  from_stop: str = ""
  to_stop: str = ""
  depart: str = ""
  arrive: str = ""
  polyline: str = ""


class Commute(BaseModel):
  minutes: int
  car_free: bool
  transfers: int
  co2_saved_kg_week: float
  steps: list[CommuteStep]
  origin_label: str = ""  # "USF campus" or "Your address" (teammate B's commute agent)


class Job(BaseModel):
  id: str
  mode: Literal["internship", "parttime"]
  title: str
  company: str
  address: str
  lat: Optional[float]
  lng: Optional[float]
  apply_url: str
  shifts: list[TimeBlock]
  pay: Optional[float]
  skills: list[str]
  match: Optional[Match]
  commute: Optional[Commute]


class Bullet(BaseModel):
  id: str  # e.g. "exp1_b2", "proj2_b1"
  text: str


class Experience(BaseModel):
  id: str  # "exp1"
  title: str
  organization: str
  location: str = ""
  start: str = ""
  end: str = ""
  bullets: list[Bullet]


class Project(BaseModel):
  id: str  # "proj1"
  name: str
  tech: list[str] = []
  bullets: list[Bullet]


class Education(BaseModel):
  school: str
  degree: str = ""
  major: str = ""
  gpa: str = ""
  graduation: str = ""  # e.g. "May 2028"
  year_in_school: str = ""  # "freshman" | "sophomore" | "junior" | "senior" | "graduate"


class Preferences(BaseModel):
  roles: list[str] = []
  preferred_cities: list[str] = []
  min_pay: Optional[float] = None
  max_commute_minutes: Optional[int] = None


class Profile(BaseModel):
  id: Optional[int] = None
  name: str
  email: str
  phone: str = ""
  address: str = ""
  work_authorization: Literal["citizen", "permanent_resident", "needs_sponsorship"]
  education: list[Education]
  experience: list[Experience]
  projects: list[Project]
  skills: list[str]
  class_schedule: list[TimeBlock]
  transportation: str = ""  # "car" | "bike" | "transit" | "walk"
  country: str = ""  # signup answer; "United States of America" derived when the address has a US state
  phone_device_type: str = ""  # signup answer, e.g. "Mobile" (apply worker fills Workday's dropdown only if set)
  how_heard: str = ""  # signup answer for "How did you hear about us?"
  preferences: Preferences
