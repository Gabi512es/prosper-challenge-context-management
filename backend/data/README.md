# Synthetic catalog

catalog.json contains 8 locations, 50 providers, 82 appointment types and 6 policy
sentences. It has duplicate provider names, multi-site providers, near-duplicate
services and capability/referral/new-patient restrictions. The explicit provider
appointment_type_ids and location_ids define eligibility; specialty is not a substitute.
Eight appointment types have no provider and remain unbookable.

The raw JSON measures 12,924 tokens; the readable historical baseline rendering is
5,894 tokens with o200k_base. At this size a full-catalog prompt fits comfortably;
the measured comparison is documented in the repository's solution.md.

The catalog is supplied data, not a patient database. demo_availability.json is a
synthetic test fixture. Live demo calls use scheduling/demo.py's seeded generator;
bookings are session-local and do not write a real calendar.
