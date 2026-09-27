import re

from .models import Profile

SKILLS = [
    "Python",
    "SQL",
    "JavaScript",
    "TypeScript",
    "React",
    "Node.js",
    "Java",
    "C++",
    "R",
    "PyTorch",
    "TensorFlow",
    "scikit-learn",
    "Docker",
    "Kubernetes",
    "AWS",
    "Azure",
    "GCP",
    "machine learning",
    "deep learning",
    "NLP",
    "LLM",
    "causal inference",
    "statistics",
    "experimentation",
    "data engineering",
    "FastAPI",
    "Django",
    "Spark",
    "dbt",
    "Tableau",
    "Power BI",
    "Git",
    "MLOps",
    "computer vision",
    "clinical research",
    "product management",
]
ROLE_GROUPS = [
    ["machine learning engineer", "ml engineer", "ai engineer", "applied scientist"],
    ["data scientist", "research scientist", "decision scientist"],
    ["software engineer", "software developer", "backend engineer", "full stack engineer"],
    ["data engineer", "analytics engineer"],
    ["data analyst", "business analyst", "product analyst"],
]


def contains(text: str, term: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", text.lower()))


def extract_profile(text: str) -> Profile:
    # Only suggest fields supported by the document; the user confirms the draft.
    skills = [skill for skill in SKILLS if contains(text, skill)]
    roles = list(
        dict.fromkeys(role for group in ROLE_GROUPS for role in group if contains(text, role))
    )
    return Profile(skills=skills, roles=roles[:5])


def match(job: dict, profile: Profile) -> dict:
    title, description = job["title"], job["description"]
    text = f"{title} {description}"
    reasons, gaps, blocked = [], [], []
    score = 0
    direct = [role for role in profile.roles if contains(title, role)]
    adjacent = any(
        any(contains(role, alias) for role in profile.roles for alias in group)
        and any(contains(title, alias) for alias in group)
        for group in ROLE_GROUPS
    )
    if direct:
        score += 35
        reasons.append(f"Title matches: {direct[0]}")
    elif adjacent:
        score += 23
        reasons.append("Title is in a related role family")
    elif profile.roles:
        gaps.append("Title is outside your target role families")
    skills = [s for s in profile.skills if contains(text, s)]
    if skills:
        score += round(35 * len(skills) / max(len(profile.skills), 1))
        reasons.append("Skills mentioned: " + ", ".join(skills[:8]))
    if profile.skills and not skills:
        gaps.append("No listed profile skills found in the description")
    location = job["location"]
    if profile.locations:
        if any(contains(location, place) for place in profile.locations):
            score += 15
            reasons.append(f"Location matches: {location}")
        elif job["workplace"] == "remote":
            gaps.append("Remote role: confirm country and work-authorization eligibility")
        elif location and location.lower() not in {"unknown", "not specified"}:
            blocked.append("Outside your selected locations")
        else:
            gaps.append("Location is not specified")
    if profile.remote == "remote" and job["workplace"] in {"onsite", "hybrid"}:
        blocked.append("Requires office attendance")
    elif profile.remote == "onsite" and job["workplace"] == "remote":
        blocked.append("Remote-only role")
    elif profile.remote != "any" and job["workplace"] == "unknown":
        gaps.append("Work arrangement is not specified")
    elif profile.remote != "any" and job["workplace"] == profile.remote:
        score += 5
        reasons.append("Work arrangement matches")
    senior = any(
        contains(title, x) for x in ["senior", "staff", "principal", "lead", "head", "director"]
    )
    junior = any(contains(title, x) for x in ["junior", "intern", "graduate", "entry level"])
    if profile.seniority == "junior" and senior:
        blocked.append("Title indicates a more senior position")
    elif profile.seniority in {"senior", "lead"} and junior:
        blocked.append("Title indicates a junior position")
    for term in profile.excluded:
        if contains(text, term):
            blocked.append(f"Contains excluded term: {term}")
    interests = [term for term in profile.interests if contains(text, term)]
    if interests:
        score += 10
        reasons.append("Interests mentioned: " + ", ".join(interests[:4]))
    if not job.get("salary"):
        gaps.append("Salary is not listed")
    if not reasons:
        reasons.append("Add target roles and skills to personalize these results")
    return {
        "score": min(score, 100),
        "reasons": reasons,
        "gaps": gaps,
        "blocked": blocked,
        "eligible": not blocked,
        "skills": skills,
    }
