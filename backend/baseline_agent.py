"""Full-catalog comparison arm; the frozen proposed implementation is untouched."""
import hashlib
import json
from dataclasses import fields, replace
from pathlib import Path

from agent_builder import AgentBuilder
from scheduling_agent import DEFAULT_SCHEDULING_AGENT_PATH, build_scheduling_tool_registry


def render_cell(value):
    if isinstance(value, tuple):
        if any(", " in item for item in value):
            raise ValueError("Ambiguous catalog list delimiter")
        value = ", ".join(value) if value else "(empty)"
    elif value is None:
        value = "(none)"
    elif isinstance(value, bool):
        value = "yes" if value else "no"
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "\\n")


def render_catalog(catalog):
    """Render every dataclass field and every policy, preserving array order."""
    lines = ["# Complete scheduling catalog", "", "Boolean values: yes/no. (none) means null; (empty) means an empty list.",
             "List items are comma-separated. IDs are authoritative; specialty is not a service-compatibility rule.", "", "## Policies"]
    lines.extend(f"{i}. {policy}" for i, policy in enumerate(catalog.policies, 1))
    for title, records in (("Locations", catalog.locations), ("Providers", catalog.providers),
                           ("Appointment types", catalog.appointment_types)):
        columns = [f.name for f in fields(records[0])]
        lines.extend(["", f"## {title}", " | ".join(columns), " | ".join("---" for _ in columns)])
        lines.extend(" | ".join(render_cell(getattr(record, name)) for name in columns) for record in records)
    return "\n".join(lines) + "\n"


def id_only_registry(engine):
    registry = build_scheduling_tool_registry(engine)
    original = registry["resolve_options"]
    properties = {k: v for k, v in original.properties.items() if not k.endswith("_query") and k != "provider_specialty"}

    async def resolve_ids(args, manager):
        rejected = sorted(set(args) - set(properties))
        if rejected:
            return {"status": "clarify", "code": "id_only_resolution", "technical_failure": False,
                    "rejected_fields": rejected, "allowed_fields": sorted(properties),
                    "next_action": "read_reference_catalog_and_submit_ids_only"}
        return await original.handler(args, manager)

    registry["resolve_options"] = replace(original, handler=resolve_ids, properties=properties,
        description="Apply IDs selected from the reference catalog and patient facts. Validate, invalidate stale state, evaluate policy and return alternatives. Free-text queries and specialty filters are forbidden.")
    return registry


def build_baseline_agent(engine, catalog, *, flow_path=DEFAULT_SCHEDULING_AGENT_PATH, availability_mode):
    if engine.catalog is not catalog:
        raise ValueError("Engine and baseline must share a catalog")
    raw = Path(flow_path).read_bytes()
    config = json.loads(raw)
    reference = render_catalog(catalog)
    # Preserve every safety/booking instruction except the catalog-access rule,
    # which must permit this arm to read its full reference rather than search.
    old = ("State a catalog fact, such as a provider's sites or services, a location's capabilities, phone or hours, or any availability, "
           "only when it appears in a tool result earlier in this conversation; otherwise call the tool first.")
    new = ("Catalog facts may come from the complete reference catalog or tool results. "
           "Availability and booking claims require tool results.")
    if old not in config["persona"]:
        raise ValueError("Frozen persona changed; baseline transformation needs review")
    persona = config["persona"].replace(old, new)
    config["persona"] = reference + "\n# Assistant role\n" + persona
    for node in config["nodes"]:
        for message in node["task_messages"]:
            content = message["content"].partition("Appointment type index:")[0].rstrip()
            content = content.replace("Use the type index below only to map a clearly named service to its ID; preserve ambiguity.",
                                      "Use the full reference catalog to resolve names to IDs; preserve ambiguity.")
            content = content.replace("Resolve provider and location through the tool; pass the provider's stated specialty even when it is worded as a practitioner noun.",
                                      "Resolve service, provider and location from the reference catalog; pass catalog IDs, never free-text queries or specialty filters.")
            message["content"] = content
    config["name"] = "Full Catalog Baseline"
    registry = id_only_registry(engine)
    builder = AgentBuilder.from_dict(config, function_registry=registry)
    builder.session_metadata = {
        "agent_id": "full_catalog_baseline",
        "agent_revision": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "availability_mode": availability_mode,
        "catalog_prefix_sha256": hashlib.sha256(reference.encode()).hexdigest(),
    }
    builder.catalog_prefix = reference
    builder.source_proposed_revision = hashlib.sha256(raw).hexdigest()
    return builder
