from __future__ import annotations

from dataclasses import dataclass
from random import Random


@dataclass(frozen=True)
class SpawnedPersonaName:
    handle: str
    display_name: str


FIRST_NAMES = (
    "Avery",
    "Blake",
    "Casey",
    "Cameron",
    "Drew",
    "Elliot",
    "Emery",
    "Finley",
    "Frankie",
    "Hayden",
    "Jamie",
    "Jordan",
    "Kai",
    "Kendall",
    "Lane",
    "Logan",
    "Morgan",
    "Noel",
    "Parker",
    "Quinn",
    "Reese",
    "Remy",
    "Riley",
    "Rowan",
    "Sage",
    "Sawyer",
    "Skyler",
    "Taylor",
    "Toby",
    "Wren",
    "Nora",
    "Maya",
    "Lena",
    "Iris",
    "Clara",
    "Mila",
    "Anya",
    "Elise",
    "Maren",
    "Talia",
    "Theo",
    "Owen",
    "Miles",
    "Caleb",
    "Jonah",
    "Felix",
    "Arlo",
    "Evan",
    "Nico",
    "Luca",
)


LAST_NAMES = (
    "Ashford",
    "Bennett",
    "Briar",
    "Brooks",
    "Calloway",
    "Carter",
    "Cross",
    "Dalton",
    "Ellis",
    "Everly",
    "Fielding",
    "Foster",
    "Grant",
    "Gray",
    "Hale",
    "Hart",
    "Hayes",
    "Keaton",
    "Kerr",
    "Langley",
    "Lennox",
    "Marlow",
    "Mercer",
    "Monroe",
    "Nolan",
    "Oakley",
    "Pierce",
    "Reid",
    "Rowe",
    "Sloane",
    "Spencer",
    "Stone",
    "Sutton",
    "Vale",
    "Vaughn",
    "Walker",
    "West",
    "Whitaker",
    "Wilder",
    "Winslow",
    "Archer",
    "Bellamy",
    "Camden",
    "Dawson",
    "Hollis",
    "Kensley",
    "Madden",
    "Pryce",
    "Ridley",
    "Tobin",
)


def generate_persona_name(
    random_source: Random,
    used_handles: set[str],
) -> SpawnedPersonaName:
    for _ in range(100):
        first_name = random_source.choice(FIRST_NAMES)
        last_name = random_source.choice(LAST_NAMES)
        suffix = _optional_numeric_suffix(random_source)
        handle = _handle(first_name, last_name, suffix)
        if handle not in used_handles:
            used_handles.add(handle)
            return SpawnedPersonaName(
                handle=handle,
                display_name=f"{first_name} {last_name}",
            )

    # Extremely unlikely fallback for large batches or unlucky seeds.
    while True:
        first_name = random_source.choice(FIRST_NAMES)
        last_name = random_source.choice(LAST_NAMES)
        handle = _handle(first_name, last_name, random_source.randint(1000, 9999))
        if handle not in used_handles:
            used_handles.add(handle)
            return SpawnedPersonaName(
                handle=handle,
                display_name=f"{first_name} {last_name}",
            )


def _optional_numeric_suffix(random_source: Random) -> int | None:
    if random_source.random() < 0.35:
        return random_source.randint(2, 99)
    return None


def _handle(first_name: str, last_name: str, suffix: int | None) -> str:
    base = f"{first_name}_{last_name}".lower()
    if suffix is None:
        return base
    return f"{base}_{suffix}"
