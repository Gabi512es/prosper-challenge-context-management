"""One catalog search for booking resolution and information lookup alike.

The core search runs first. Only when it finds nothing may a site or service
match by its words ("Mission District Clinic" -> "Mission District Family
Clinic", "mid town" -> Midtown), and a service described in the caller's own
words get suggestions to confirm. Providers keep the core's own suggestions.
"""
from difflib import SequenceMatcher
import re

from scheduling.catalog import _normalize
from .speech import words_of

FILLER = {'the', 'a', 'an', 'of', 'at', 'in', 'on', 'for', 'my', 'your', 'please'}
GENERIC = {'location': {'clinic', 'office', 'location', 'site', 'center', 'centre'},
           'appointment_type': {'appointment', 'visit'}}
SITE_GENERIC = {'medical', 'group', 'center', 'centre', 'clinic', 'health', 'care', 'family', 'specialty',
                'the', 'of', 'and'}
# Words too common to suggest a service on their own ("check" -> Pacemaker Check).
WEAK_SERVICE = {'check', 'checkup', 'up', 'general', 'visit', 'exam', 'test', 'consultation', 'consult',
                'appointment', 'follow', 'session', 'evaluation', 'routine', 'regular', 'basic'}
# Everyday names for a routine visit.
CHECKUP = re.compile(r"\b(check[- ]?up|yearly|annual|routine (exam|visit))\b", re.I)
CHECKUP_SERVICES = ('Annual Physical', 'Annual Wellness Visit')


def same_stem(word, other):
    """One word and an inflection of it ("vaccine", "vaccination"): a shared start of
    five letters or more. Stricter than spelling similarity ("neurology" and "urology"
    share none)."""
    if word == other:
        return True
    n = 0
    for a, b in zip(word, other):
        if a != b:
            break
        n += 1
    return n >= 5


def site_words(name):
    return set(words_of(name)) - SITE_GENERIC


def matching_sites(locations, text):
    """Sites whose distinctive words all occur in the text, ignoring spaces, case
    and small speech-to-text distortions ("mid town", "admission bay")."""
    words = [w for w in words_of(text or '') if w not in SITE_GENERIC]
    candidates = set(words) | {a + b for a, b in zip(words, words[1:])}

    def heard(word):
        return word in candidates or (len(word) > 3 and any(
            len(c) > 3 and SequenceMatcher(None, word, c).ratio() >= 0.8 for c in candidates))
    return [location for location in locations if site_words(location.name)
            and all(heard(word) for word in site_words(location.name))]


class CatalogMatcher:
    """Wraps the engine's catalog; every other attribute is the catalog's own."""
    def __init__(self, catalog):
        self._catalog = catalog

    def __getattr__(self, name):
        if name == '_catalog':
            raise AttributeError(name)
        return getattr(self._catalog, name)

    def search(self, entity, query, *, specialty=None):
        matches = self._catalog.search(entity, query, specialty=specialty)
        if matches or entity == 'provider':
            return matches
        words = set(_normalize(query).split()) - FILLER - GENERIC.get(entity, set())
        if not words:
            return []
        matches = self._by_words(entity, words) or self._spoken_site(entity, query)
        if matches or entity != 'appointment_type':
            return matches
        return self._service_suggestions(query, words)

    def _by_words(self, entity, words):
        found = [self._catalog.summary(entity, item.id) for item in self._catalog._collection(entity)
                 if words <= set(_normalize(item.name).split())]
        if found or entity != 'appointment_type':
            return found
        # Every word the caller said is in one service's name, up to inflection
        # ("travel vaccine consult" -> Travel Vaccination Consult): that service.
        # Common words ("check", "consult") must be said as they are, and one other word is needed.
        if not words - WEAK_SERVICE:
            return []
        match = lambda w, n: w == n if w in WEAK_SERVICE else same_stem(w, n)
        stems = [item for item in self._catalog._collection(entity)
                 if all(any(match(w, n) for n in _normalize(item.name).split()) for w in words)]
        return [self._catalog.summary(entity, stems[0].id)] if len(stems) == 1 else []

    def _spoken_site(self, entity, query):
        if entity != 'location':
            return []
        sites = matching_sites(self._catalog._collection(entity), query)
        return [self._catalog.summary(entity, sites[0].id)] if len(sites) == 1 else []

    def _suggestion(self, ident):
        return {**self._catalog.summary('appointment_type', ident), 'match_kind': 'suggestion',
                'requires_confirmation': True}

    def routine_options_for_provider(self, query, provider):
        """Expand an already generic routine request from catalog relationships.

        No child-service alias or clinical choice is inferred. All returned
        services are suggestions the resolved provider actually offers.
        """
        words = set(_normalize(query).split()) - FILLER - GENERIC['appointment_type']
        if not CHECKUP.search(query) or words - WEAK_SERVICE - {'yearly', 'annual', 'routine'}:
            return []
        return [self._suggestion(t.id) for t in self._catalog.appointment_types
                if t.id in provider.appointment_type_ids and t.specialty == provider.specialty]

    def _service_suggestions(self, query, words):
        """A service described in the caller's own words ("a full skin check")."""
        collection = self._catalog._collection('appointment_type')
        if CHECKUP.search(query) and not words - WEAK_SERVICE - {'yearly', 'annual', 'routine'}:
            return [self._suggestion(item.id) for item in collection if item.name in CHECKUP_SERVICES]
        scored = []
        similar = lambda w, n: same_stem(w, n) or SequenceMatcher(None, w, n).ratio() >= 0.8
        for item in collection:
            name_words = set(_normalize(item.name).split())
            hits = frozenset(w for w in words - WEAK_SERVICE if len(w) > 2 and any(similar(w, n) for n in name_words))
            if hits:
                # The name that matches most of the caller's words first; common words
                # ("consult") only break ties.
                weak = sum(1 for w in words & WEAK_SERVICE if any(similar(w, n) for n in name_words))
                scored.append((-len(hits), -weak, item.id, hits))
        scored.sort(key=lambda row: row[:3])
        # Suggestions share a matched word with the best one ("skin"), so an
        # incidental word ("check" -> Pacemaker Check) does not add noise.
        best = scored[0][3] if scored else frozenset()
        return [self._suggestion(ident) for _, _, ident, hits in scored if hits & best][:3]
