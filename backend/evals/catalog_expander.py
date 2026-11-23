"""Deterministic disconnected catalog distractors; never edits the source catalog."""
from copy import deepcopy
from hashlib import sha256
from itertools import product
import json
import re

EXPANDER_VERSION = "catalog-disjoint-v1"
SEED = 20261109
COLLECTIONS = ("locations", "providers", "appointment_types")
MAX_FACTOR = 50

PLACE_LEFT = "Amber Aspen Azure Birch Briar Cedar Copper Coral Crystal Elm Falcon Fern Garnet Hazel Holly Indigo Ivy Jade Juniper Larch Laurel Maple Moss Oak Olive Onyx Opal Pine Quartz Robin Rowan Sage Silver Spruce Teal Topaz Willow Wren Yarrow Zircon".split()
PLACE_RIGHT = "Arbor Bend Bluff Brook Cove Creek Crossing Dale Field Ford Glen Grove Heath Hollow Knoll Landing Meadow Mill Orchard Park Pass Point Ridge Rise Run Terrace Vale View Walk Way Wood Yard".split()
FIRST_NAMES = "Aaron Adele Agnes Ansel Arden Basil Beatrice Boris Celia Clyde Daphne Edith Eileen Elise Elsie Emmett Estelle Felix Flora Gideon Greta Hazel Hector Hugo Inez Iris Ivan Jonah Jude Laurel Leona Lionel Louisa Lucian Mabel Mara Marcel Nadia Nell Noel Orla Otis Pearl Quentin Reed Rex Rhoda Rosa Ruth Selma Silas Thea Vera Viola Walter Winona Abel Ada Alistair Amos Anita Astrid Calvin Cedric Clive Cora Dorian Edgar Edmund Enid Eugene Faye Fergus Florence Frida Gerard Gilbert Gloria Harvey Henrietta Horace Irene Jasper Jocelyn Judith Leon Leonard Lucille Lydia Magnus Malcolm Maude Milton Miriam Myrtle Nathan Nigel Nora Oswald Percy Petra Phoebe Roland Rosalie Rowan Saskia Stella Tabitha Tobias Ursula Victor Wilfred Yvonne Zara".split()
SURNAME_LEFT = "Alder Bancroft Cavend Dun Ellis Fair Gran Haver Kings Lark Linden Mere Quill Ravens Stans Thorn Under West Whit Wood".split()
SURNAME_RIGHT = "brook croft dale field ford gate grove hall haven hurst land ley mere mont ridge stead stone vale well wick wood worth".split()
TOPICS = "Acoustics Agronomy Botany Ceramics Ecology Entomology Ethology Forestry Geodesy Geology Hydrology Metallurgy Mineralogy Oceanography Optics Ornithology Phonetics Robotics Seismology Textiles Topography Tribology Zoology Cartography Crystallography Dendrology Floriculture Gemology Limnology Meteorology Mycology Paleontology".split()
ACTIVITIES = "Assessment Review Survey Study Workshop Session Evaluation Consultation Planning Analysis Check Demonstration Training Inspection Mapping Orientation".split()


def canonical_bytes(document):
    return json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _words(value):
    return set(re.findall(r"[a-z0-9]+", value.casefold())) - {"dr", "doctor"}


def _ordered(values, seed, category):
    # Hash ranking is stable across processes/Python RNG implementations.
    return sorted(values, key=lambda text: (sha256(f"{EXPANDER_VERSION}|{seed}|{category}|{text}".encode()).digest(), text))


def expand_catalog(source, factor, *, seed=SEED, reserved_names=()):
    """Exact entity-count multiplier; additions are isolated copies with new names/IDs.

    Policies and every original record are retained verbatim as a list prefix.
    Synthetic names describe fictional research services, not clinical facts.
    No new provider can offer an original service or practice at an original site.
    """
    if isinstance(factor, bool) or not isinstance(factor, int) or not 1 <= factor <= MAX_FACTOR:
        raise ValueError(f"factor must be an integer from 1 to {MAX_FACTOR}")
    expanded = deepcopy(source)
    original_names = {item["name"].casefold() for key in COLLECTIONS for item in source[key]}
    protected = original_names | {name.casefold() for name in reserved_names}
    forbidden_person_words = set().union(*(_words(p["name"]) for p in source["providers"]),
                                         *(_words(name) for name in reserved_names))
    people = [f"Dr. {first} {left}{right}" for first, left, right in product(FIRST_NAMES, SURNAME_LEFT, SURNAME_RIGHT)
              if not _words(f"{first} {left}{right}").intersection(forbidden_person_words)]
    pools = {
        "locations": _ordered([f"{left} {right} Health Center" for left, right in product(PLACE_LEFT, PLACE_RIGHT)], seed, "locations"),
        "providers": _ordered(people, seed, "providers"),
        "appointment_types": _ordered([f"Research {modifier} {topic} {activity}" for modifier, topic, activity
                                       in product(PLACE_LEFT, TOPICS, ACTIVITIES)], seed, "appointment_types"),
    }
    for key in COLLECTIONS:
        pools[key] = [name for name in pools[key] if name.casefold() not in protected]
        if len(pools[key]) < len(source[key]) * (factor - 1):
            raise ValueError(f"Insufficient unique synthetic {key} names")
    starts = {key: max(int(item["id"].rsplit("_", 1)[1]) for item in source[key]) + 1 for key in COLLECTIONS}
    prefixes = {"locations": "loc", "providers": "prov", "appointment_types": "appt"}
    for block in range(factor - 1):
        maps = {key: {item["id"]: f"{prefixes[key]}_{starts[key] + block * len(source[key]) + i:03d}"
                      for i, item in enumerate(source[key])} for key in COLLECTIONS}
        for key in COLLECTIONS:
            for i, original in enumerate(source[key]):
                serial = block * len(source[key]) + i
                record = deepcopy(original)
                record.update(id=maps[key][original["id"]], name=pools[key][serial])
                if key == "locations":
                    record.update(address=f"{100 + serial} Research Way", city="Alderhaven",
                                  phone=f"(202) 555-01{serial % 100:02d}")
                elif key == "providers":
                    record["location_ids"] = [maps["locations"][value] for value in original["location_ids"]]
                    record["appointment_type_ids"] = [maps["appointment_types"][value] for value in original["appointment_type_ids"]]
                expanded[key].append(record)
    validate_expansion(source, expanded, factor, reserved_names=reserved_names)
    return expanded


def validate_expansion(source, expanded, factor, *, reserved_names=()):
    if set(source) != set(expanded) or source["policies"] != expanded["policies"]:
        raise ValueError("Source fields/policies changed")
    protected = {item["name"].casefold() for key in COLLECTIONS for item in source[key]} | {n.casefold() for n in reserved_names}
    additions = {}
    new_names = set()
    for key in COLLECTIONS:
        original = source[key]
        if expanded[key][:len(original)] != original or len(expanded[key]) != len(original) * factor:
            raise ValueError(f"Original {key} or multiplier changed")
        ids = [item["id"] for item in expanded[key]]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Duplicate {key} ID")
        additions[key] = set(ids[len(original):])
        for item in expanded[key][len(original):]:
            name = item["name"].casefold()
            if name in protected or name in new_names:
                raise ValueError("Synthetic name collision")
            new_names.add(name)
    for provider in expanded["providers"][len(source["providers"]):]:
        if not set(provider["location_ids"]) <= additions["locations"] or not set(provider["appointment_type_ids"]) <= additions["appointment_types"]:
            raise ValueError("Synthetic provider bridges into original catalog")


def expansion_manifest(source, expanded, factor, *, seed=SEED):
    return {
        "expander_version": EXPANDER_VERSION, "seed": seed, "factor": factor,
        "base_document_sha256": sha256(canonical_bytes(source)).hexdigest(),
        "expanded_document_sha256": sha256(canonical_bytes(expanded)).hexdigest(),
        "original_counts": {key: len(source[key]) for key in COLLECTIONS},
        "expanded_counts": {key: len(expanded[key]) for key in COLLECTIONS},
        "policies": "unchanged", "availability": "original closed-world fixtures only",
        "relations": "original records retained; additions are disconnected copies",
        "naming": "seeded hash order, fictional research-service distractors, ordinary sequential IDs",
    }
