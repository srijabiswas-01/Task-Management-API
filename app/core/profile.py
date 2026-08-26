from app.models import User, UserProfile


PROFILE_FIELDS = (
    ("name", "Full name"),
    ("profile_image", "Profile photo"),
    ("phone", "Phone"),
    ("location", "Location"),
    ("bio", "About me"),
    ("professional_title", "Designation"),
    ("department", "Department"),
    ("years_experience", "Years of experience"),
    ("skills", "Skills"),
    ("achievements", "Achievements"),
)


def profile_completion(user: User, profile: UserProfile | None = None) -> tuple[int, list[str]]:
    profile = profile or user.profile
    missing: list[str] = []
    for field, label in PROFILE_FIELDS:
        value = user.name if field == "name" else getattr(profile, field, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(label)
    completed = len(PROFILE_FIELDS) - len(missing)
    return round(completed / len(PROFILE_FIELDS) * 100), missing
