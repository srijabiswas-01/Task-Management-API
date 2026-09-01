import base64
import struct

from fastapi import HTTPException

from app.models import User, UserProfile


PROFILE_FIELDS = (
    ("name", "Full name"),
    ("profile_image", "Profile photo"),
    ("phone", "Phone"),
    ("location_city", "City"),
    ("location_state", "State"),
    ("location_country", "Country"),
    ("professional_title", "Designation"),
    ("department", "Department"),
    ("experience_start_date", "Experience start date"),
    ("skills", "Skills"),
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


def validate_profile_image(value: str | None) -> None:
    if not value:
        return
    try:
        header, encoded = value.split(",", 1)
        mime = header.split(";", 1)[0].removeprefix("data:")
        if ";base64" not in header or mime not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError
        data = base64.b64decode(encoded, validate=True)
        if len(data) > 2 * 1024 * 1024:
            raise HTTPException(status_code=422, detail="Profile image must not exceed 2 MB")
        width = height = 0
        if mime == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", data[16:24])
        elif mime == "image/webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            if data[12:16] == b"VP8X":
                width = 1 + int.from_bytes(data[24:27], "little")
                height = 1 + int.from_bytes(data[27:30], "little")
            elif data[12:16] == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
                width = int.from_bytes(data[26:28], "little") & 0x3FFF
                height = int.from_bytes(data[28:30], "little") & 0x3FFF
            elif data[12:16] == b"VP8L" and data[20] == 0x2F:
                bits = int.from_bytes(data[21:25], "little")
                width = 1 + (bits & 0x3FFF)
                height = 1 + ((bits >> 14) & 0x3FFF)
        elif mime == "image/jpeg" and data[:2] == b"\xff\xd8":
            offset = 2
            while offset + 9 < len(data):
                if data[offset] != 0xFF:
                    offset += 1; continue
                marker = data[offset + 1]
                length = int.from_bytes(data[offset + 2:offset + 4], "big")
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    height = int.from_bytes(data[offset + 5:offset + 7], "big")
                    width = int.from_bytes(data[offset + 7:offset + 9], "big")
                    break
                offset += 2 + length
        if width < 128 or height < 128:
            raise HTTPException(status_code=422, detail="Profile image must be at least 128 × 128 pixels")
    except HTTPException:
        raise
    except (ValueError, TypeError, IndexError, struct.error) as error:
        raise HTTPException(status_code=422, detail="Profile image must be a valid PNG, JPG or WebP data image") from error
