from .models import Profile, Source


def seed_demo(store):
    if store.setting("demo_seeded"):
        return
    store.save_profile(
        Profile(
            name="Alex",
            roles=["Machine learning engineer", "Data scientist"],
            skills=["Python", "SQL", "PyTorch", "statistics", "causal inference"],
            locations=["Copenhagen", "Europe"],
            interests=["healthcare", "climate"],
        )
    )
    data = [
        (
            "Northstar Health",
            "Senior Machine Learning Engineer",
            "Copenhagen, Denmark",
            "hybrid",
            "DKK 650,000–850,000 / year",
            "Build machine learning systems that help clinicians make better decisions. "
            "Work with Python, SQL and PyTorch on healthcare data. Experience in "
            "statistics, causal inference and production model evaluation is valued. Three "
            "days a week in our Copenhagen office.",
        ),
        (
            "Canopy Labs",
            "Data Scientist — Climate",
            "Remote, Europe",
            "remote",
            "EUR 70,000–95,000 / year",
            "Use Python, SQL, statistics and causal inference to understand the impact of "
            "climate interventions. Partner with researchers and engineers to design "
            "experiments. Remote within Europe; work authorization in your country of "
            "residence is required.",
        ),
        (
            "Fieldwork",
            "Applied Scientist",
            "Copenhagen, Denmark",
            "hybrid",
            "",
            "Develop decision systems for logistics using machine learning. You will use "
            "Python, PyTorch and SQL to build models and evaluate them in production. We "
            "value rigorous statistics and thoughtful experimentation.",
        ),
        (
            "Harbor Analytics",
            "Data Scientist",
            "Remote, Europe",
            "remote",
            "",
            "Help healthcare teams understand care pathways using Python and SQL. Design "
            "observational studies and explain their limitations. Experience with causal "
            "inference and statistics is a plus.",
        ),
        (
            "Orbit Systems",
            "Staff ML Engineer",
            "San Francisco, US",
            "onsite",
            "USD 190,000–230,000 / year",
            "Lead a team deploying PyTorch and Python systems. This role requires "
            "attendance at our San Francisco office. Experience with SQL and statistics "
            "required.",
        ),
        (
            "Moss Studio",
            "Frontend Engineer",
            "Copenhagen, Denmark",
            "hybrid",
            "",
            "Build accessible interfaces in React and TypeScript. Work with product "
            "designers to improve the customer experience.",
        ),
    ]
    for i, (company, title, location, arrangement, salary, description) in enumerate(data):
        store.add_source(Source(provider="greenhouse", board=f"demo-{i}", company=company))
        source = next(s for s in store.sources() if s["board"] == f"demo-{i}")
        store.ingest(
            source["id"],
            [
                {
                    "external_id": f"demo-{i}",
                    "company": company,
                    "title": title,
                    "location": location,
                    "workplace": arrangement,
                    "salary": salary,
                    "description": description,
                    "published": None,
                    "url": f"https://example.com/demo-job-{i}",
                }
            ],
        )
    store.set_setting("demo_seeded", True)
