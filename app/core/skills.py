def parse_skills(value: str | None) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    skills: list[str] = []
    for raw in value.replace("\n", ",").split(","):
        name = " ".join(raw.strip().split())
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            skills.append(name)
    return skills


def normalize_skills(value: str | None) -> str | None:
    skills = parse_skills(value)
    return ", ".join(skills) if skills else None
