from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from random import Random


@dataclass(frozen=True)
class SpawnedPersonaName:
    handle: str
    display_name: str


@dataclass(frozen=True)
class NamePool:
    given_names: tuple[str, ...]
    family_names: tuple[str, ...]
    family_name_first: bool = False


# Names are kept in compatible regional pools so generated display names feel
# coherent. They are intentionally bundled with the worker: generation remains
# deterministic, works offline, and does not send account data to a name API.
NAME_POOLS = (
    NamePool(
        given_names=(
            "Aiden", "Amelia", "Callum", "Chloe", "Conor", "Daisy", "Ellis", "Erin",
            "Finn", "Freya", "Grace", "Harry", "Imogen", "Jamie", "Lewis", "Maeve",
            "Niamh", "Orla", "Oscar", "Rory", "Saoirse", "Theo", "Willow", "Zara",
        ),
        family_names=(
            "Bennett", "Brooks", "Campbell", "Clarke", "Collins", "Doyle", "Evans",
            "Fletcher", "Foster", "Gallagher", "Graham", "Hayes", "Hughes", "Kelly",
            "Kerr", "Morgan", "Murray", "O'Brien", "Reid", "Scott", "Walsh", "Ward",
        ),
    ),
    NamePool(
        given_names=(
            "Adaeze", "Ade", "Amara", "Amina", "Ayomide", "Chidi", "Damilola",
            "Efe", "Emeka", "Folake", "Ife", "Ikenna", "Kemi", "Kwame", "Mariam",
            "Nana", "Nneka", "Olamide", "Sade", "Tobi", "Yaa", "Zainab",
        ),
        family_names=(
            "Abiola", "Adebayo", "Adeyemi", "Boateng", "Chukwu", "Diallo", "Eze",
            "Kamara", "Mensah", "Nwosu", "Obi", "Okafor", "Okeke", "Osei", "Sarpong",
            "Sesay", "Sow", "Traore", "Yeboah", "Yusuf",
        ),
    ),
    NamePool(
        given_names=(
            "Aarav", "Aisha", "Akash", "Anika", "Arjun", "Dev", "Diya", "Farah",
            "Ishaan", "Kabir", "Kiran", "Meera", "Mira", "Neha", "Nikhil", "Priya",
            "Ravi", "Rohan", "Sana", "Simran", "Tara", "Zoya",
        ),
        family_names=(
            "Ahmed", "Bose", "Chandra", "Das", "Gill", "Gupta", "Iyer", "Joshi",
            "Kapoor", "Kaur", "Khan", "Malik", "Mehta", "Nair", "Patel", "Rao",
            "Shah", "Sharma", "Singh", "Verma",
        ),
    ),
    NamePool(
        given_names=(
            "Amal", "Amir", "Aya", "Farid", "Hana", "Idris", "Karim", "Laila",
            "Leila", "Mariam", "Nadia", "Nour", "Omar", "Rami", "Rania", "Salma",
            "Sami", "Samira", "Tariq", "Yara", "Yasmin", "Zayd",
        ),
        family_names=(
            "Abbas", "Darwish", "Farah", "Haddad", "Hakim", "Hamdan", "Hassan",
            "Ibrahim", "Khalil", "Mansour", "Nasser", "Qasim", "Rahman", "Saleh",
            "Shafiq", "Suleiman", "Zaman", "Zayed",
        ),
    ),
    NamePool(
        given_names=(
            "Alejandro", "Alma", "Camila", "Carmen", "Diego", "Elena", "Emilio",
            "Ines", "Javier", "Lucia", "Mateo", "Nico", "Noelia", "Pablo", "Paloma",
            "Raul", "Rocio", "Sergio", "Sofia", "Valeria", "Ximena", "Yago",
        ),
        family_names=(
            "Alonso", "Castillo", "Cruz", "Delgado", "Diaz", "Dominguez", "Flores",
            "Garcia", "Herrera", "Iglesias", "Lopez", "Marin", "Mendez", "Morales",
            "Navarro", "Ortega", "Reyes", "Rojas", "Romero", "Santos", "Vega",
        ),
    ),
    NamePool(
        given_names=(
            "Alessia", "Andrea", "Bianca", "Chiara", "Dario", "Elisa", "Enzo", "Fabio",
            "Giada", "Giorgio", "Lorenzo", "Luca", "Marco", "Matteo", "Nadia", "Piero",
            "Renata", "Sara", "Sofia", "Tommaso", "Viola", "Vittoria",
        ),
        family_names=(
            "Bianchi", "Bruno", "Colombo", "Conti", "Costa", "De Luca", "Esposito",
            "Ferrari", "Fontana", "Gallo", "Greco", "Lombardi", "Mancini", "Marino",
            "Moretti", "Ricci", "Romano", "Rossi", "Russo", "Villa",
        ),
    ),
    NamePool(
        given_names=(
            "Adrian", "Aneta", "Bartosz", "Daria", "Dominik", "Elena", "Emil", "Irena",
            "Jakub", "Karolina", "Kasia", "Luka", "Marek", "Marta", "Milan", "Niko",
            "Petra", "Sasha", "Tomas", "Viktor", "Zofia", "Zora",
        ),
        family_names=(
            "Babić", "Horvat", "Janković", "Kovač", "Kowalski", "Marković", "Nagy",
            "Nikolić", "Novak", "Nowak", "Pavlov", "Petrov", "Popović", "Savić",
            "Stojanović", "Varga", "Vuković", "Zieliński",
        ),
    ),
    NamePool(
        given_names=(
            "Alva", "Astrid", "Elias", "Elin", "Emil", "Freja", "Hanna", "Henrik",
            "Ida", "Isak", "Klara", "Lars", "Linnea", "Mads", "Nils", "Oskar",
            "Signe", "Soren", "Tove", "Viggo",
        ),
        family_names=(
            "Andersen", "Berg", "Dahl", "Eriksen", "Hansen", "Haugen", "Holm", "Jensen",
            "Johansson", "Larsen", "Lindberg", "Lund", "Madsen", "Nielsen", "Nyberg",
            "Olsen", "Svensson", "Thorsen",
        ),
    ),
    NamePool(
        given_names=(
            "Aiko", "Akira", "Emi", "Haruka", "Hina", "Hiro", "Kaori", "Kenta", "Mai",
            "Naoki", "Ren", "Riku", "Rina", "Saki", "Shin", "Sora", "Takumi", "Yui",
        ),
        family_names=(
            "Aoki", "Fujita", "Hayashi", "Ito", "Kato", "Kobayashi", "Mori", "Nakamura",
            "Saito", "Sato", "Suzuki", "Takahashi", "Tanaka", "Watanabe", "Yamamoto",
        ),
        family_name_first=True,
    ),
    NamePool(
        given_names=(
            "Ara", "Dae", "Eunji", "Hana", "Hyejin", "Jisoo", "Joon", "Junho", "Minho",
            "Minji", "Nari", "Seojun", "Sora", "Sujin", "Taeyang", "Yejin", "Yuna",
        ),
        family_names=(
            "Bae", "Choi", "Han", "Hwang", "Jeong", "Kang", "Kim", "Kwon", "Lee",
            "Lim", "Moon", "Park", "Shin", "Song", "Yoon",
        ),
        family_name_first=True,
    ),
)

# Retained as flattened public constants for callers that use the corpus.
FIRST_NAMES = tuple(name for pool in NAME_POOLS for name in pool.given_names)
LAST_NAMES = tuple(name for pool in NAME_POOLS for name in pool.family_names)

_HANDLE_CLEANUP = re.compile(r"[^a-z0-9]+")
_HANDLE_STYLES = (
    ("dot", 22),
    ("underscore", 21),
    ("joined", 18),
    ("dash", 14),
    ("initial_family", 10),
    ("given_initial", 8),
    ("family_given", 7),
)


def generate_persona_name(
    random_source: Random,
    used_handles: set[str],
) -> SpawnedPersonaName:
    for _ in range(200):
        pool = random_source.choice(NAME_POOLS)
        given_name = random_source.choice(pool.given_names)
        family_name = random_source.choice(pool.family_names)
        display_name = _display_name(pool, given_name, family_name, random_source)
        handle = _handle(given_name, family_name, random_source)
        if handle not in used_handles:
            used_handles.add(handle)
            return SpawnedPersonaName(handle=handle, display_name=display_name)

    # Very large batches can exhaust common unnumbered forms. A wider suffix
    # preserves uniqueness without exposing a sequential "bot number".
    while True:
        pool = random_source.choice(NAME_POOLS)
        given_name = random_source.choice(pool.given_names)
        family_name = random_source.choice(pool.family_names)
        display_name = _display_name(pool, given_name, family_name, random_source)
        base = _format_handle(given_name, family_name, _weighted_style(random_source))
        handle = f"{base}{random_source.randint(1000, 99999)}"[:64]
        if handle not in used_handles:
            used_handles.add(handle)
            return SpawnedPersonaName(handle=handle, display_name=display_name)


def _display_name(
    pool: NamePool,
    given_name: str,
    family_name: str,
    random_source: Random,
) -> str:
    parts = (family_name, given_name) if pool.family_name_first else (given_name, family_name)
    # A small proportion of profiles use a middle initial, as real account
    # display names often do. Handles deliberately remain based on two names.
    if random_source.random() < 0.08:
        return f"{parts[0]} {random_source.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}. {parts[1]}"
    return " ".join(parts)


def _handle(given_name: str, family_name: str, random_source: Random) -> str:
    base = _format_handle(given_name, family_name, _weighted_style(random_source))
    if random_source.random() >= 0.29:
        return base[:64]

    suffix_style = random_source.random()
    if suffix_style < 0.50:
        suffix = str(random_source.randint(2, 99))
    elif suffix_style < 0.82:
        suffix = str(random_source.randint(1980, 2006))
    else:
        suffix = f"{random_source.randint(0, 9999):04d}"

    separator = random_source.choices(("", "_", ".", "-"), weights=(55, 19, 14, 12), k=1)[0]
    return f"{base}{separator}{suffix}"[:64]


def _format_handle(given_name: str, family_name: str, style: str) -> str:
    given = _slug_part(given_name)
    family = _slug_part(family_name)
    if style == "dot":
        return f"{given}.{family}"
    if style == "underscore":
        return f"{given}_{family}"
    if style == "dash":
        return f"{given}-{family}"
    if style == "initial_family":
        return f"{given[0]}.{family}"
    if style == "given_initial":
        return f"{given}{family[0]}"
    if style == "family_given":
        return f"{family}.{given}"
    return f"{given}{family}"


def _slug_part(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return _HANDLE_CLEANUP.sub("", ascii_value.casefold())


def _weighted_style(random_source: Random) -> str:
    styles, weights = zip(*_HANDLE_STYLES, strict=True)
    return random_source.choices(styles, weights=weights, k=1)[0]
