"""Zero-API catalog measurements and explicitly hypothetical spend projections."""
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import tiktoken

from baseline_agent import render_catalog
from scheduling import load_catalog
from .catalog_expander import COLLECTIONS, EXPANDER_VERSION, SEED, canonical_bytes, expand_catalog, expansion_manifest
from .dev_matrix import PRICE_DATE, PRICE_PER_MILLION, usage_for_call
from .loader import DEFAULT_CATALOG_PATH, DEFAULT_SCENARIOS_PATH, git_blob_sha, load_dev_scenarios

BACKEND = Path(__file__).resolve().parents[1]
CASES = ("DEV-002", "DEV-003", "DEV-009", "DEV-012")
CONTEXT_LIMIT = 128000
OUTPUT_RESERVE = 512
INDEX_VERSION = "scaled-index-v3-id-name-search-only"
INDEX_FIELDS = ("id", "name")
INDEX_MARKER = "Appointment type index:"
PROFILES = {
    "proposed-v2": "comparison-proposed-v2-20261109-180827-8752c3",
    "baseline": "comparison-baseline-20261109-182321-c4ee5f",
}


def index_message(config):
    messages = [message for node in config["nodes"] for message in node["task_messages"]
                if INDEX_MARKER in message["content"]]
    if len(messages) != 1:
        raise ValueError("Expected exactly one appointment type index")
    return messages[0]


def render_type_index(document):
    return json.dumps([{key: item[key] for key in INDEX_FIELDS} for item in document["appointment_types"]],
                      ensure_ascii=False, separators=(",", ":"))


def experiment_agent(config, document):
    """Replace index data only; every instruction and all other config stays exact."""
    derived = deepcopy(config)
    message = index_message(derived)
    prefix, marker, old_data = message["content"].partition(INDEX_MARKER)
    json.loads(old_data)  # Fail rather than accidentally discard trailing instructions.
    message["content"] = prefix + marker + " " + render_type_index(document)
    return derived


def search_only_agent(config):
    """Exploratory copy: remove the index and replace only its access instruction."""
    derived = deepcopy(config)
    message = index_message(derived)
    prefix, _, data = message["content"].partition(INDEX_MARKER)
    json.loads(data)
    old = "Use the type index below only to map a clearly named service to its ID; preserve ambiguity."
    if prefix.count(old) != 1:
        raise ValueError("Frozen index-access instruction changed")
    message["content"] = prefix.replace(old,
        "Resolve services, providers and locations with resolve_options free-text queries; preserve ambiguity.").rstrip()
    return derived


def cache_billing(usage):
    """GPT-4o Chat Completions exposes reads, not separately metered writes.

    Uncached input includes cache-populating work. It cannot be attributed to
    cache creation from prompt-minus-cached, and must not be charged twice.
    """
    prices = PRICE_PER_MILLION
    return {
        "actual_cached_tokens": usage["cached_tokens"],
        "actual_cached_input_cost_usd": (usage["cached_tokens"] * prices["cached_input"] / 1_000_000
                                         if usage["cached_tokens"] is not None else None),
        "actual_uncached_input_cost_usd": (usage["uncached_prompt_tokens"] * prices["uncached_input"] / 1_000_000
                                           if usage["uncached_prompt_tokens"] is not None else None),
        "cache_write_tokens": None,
        "cache_write_input_cost_usd": None,
        "cache_write_surcharge_usd": 0,
        "write_accounting": "Not separately reported by GPT-4o Chat Completions; included in uncached input, no extra write fee.",
    }


def reserved_names(dataset):
    return sorted({s["patient_facts"][key] for s in dataset["scenarios"] for key in ("name", "provider_name")
                   if isinstance(s["patient_facts"].get(key), str)})


def profiles_from_saved_logs():
    profiles = {}
    for arm, run_id in PROFILES.items():
        report = json.loads((BACKEND / "logs/evals" / f"{run_id}.results.json").read_text())
        runs = [r for r in report["runs"] if r["scenario_id"] in CASES]
        if len(runs) != 12 or any(r.get("unreported_model_calls") for r in runs):
            raise ValueError("Projection requires all three prior repetitions of the four cases with known usage")
        calls = {r["call_id"] for r in runs}
        rows = [json.loads(line) for line in Path(report["metrics_path"]).read_text().splitlines()]
        rows = [row for row in rows if row["call_id"] in calls]
        usage = usage_for_call(rows)
        if usage["cost_usd"] is None:
            raise ValueError("Projection profile has missing usage")
        profiles[arm] = {
            "source_run_id": run_id, "repetitions": 3, **usage, "cache_billing": cache_billing(usage),
            "cached_fraction": usage["cached_tokens"] / usage["prompt_tokens"],
            "max_prompt_tokens": max(row["prompt_tokens"] for row in rows),
            "max_startup_prompt_tokens": max(row["prompt_tokens"] for row in rows if row["patient_turn"] == 0),
            "max_startup_cached_tokens": max(row["cached_tokens"] for row in rows if row["patient_turn"] == 0),
        }
    return profiles


def project(profile, prefix_delta, repetitions):
    """Same call/output/history shape as 1x logs; cache share also held constant."""
    weight = repetitions / profile["repetitions"]
    calls = profile["model_calls"] * weight
    prompt = profile["prompt_tokens"] * weight + calls * prefix_delta
    cached = profile["cached_tokens"] * weight + calls * prefix_delta * profile["cached_fraction"]
    completion = profile["completion_tokens"] * weight
    prices = PRICE_PER_MILLION
    # One cold new-scale prefix, on top of the observed average cache pattern.
    cold_start_premium = (profile["max_startup_cached_tokens"] + prefix_delta * profile["cached_fraction"]) * (prices["uncached_input"] - prices["cached_input"]) / 1_000_000
    warm = ((prompt - cached) * prices["uncached_input"] + cached * prices["cached_input"] + completion * prices["output"]) / 1_000_000 + cold_start_premium
    cold = (prompt * prices["uncached_input"] + completion * prices["output"]) / 1_000_000
    max_request = profile["max_prompt_tokens"] + prefix_delta + OUTPUT_RESERVE
    fits = max_request <= CONTEXT_LIMIT
    return {
        "kind": "projection, not a paid measurement", "conversations": len(CASES) * repetitions,
        "expected_model_calls": round(calls, 3), "projected_prompt_tokens": round(prompt),
        "projected_cached_tokens": round(cached),
        "actual_cached_tokens": None, "cache_write_tokens": None, "cache_write_input_cost_usd": None,
        "cache_write_surcharge_usd": 0,
        "projected_max_input_plus_output_reserve": max_request,
        "fits_observed_history_shape": fits,
        "projected_usd_with_observed_cache_share": round(warm, 6) if fits else None,
        "projected_usd_with_no_cache": round(cold, 6) if fits else None,
        "hypothetical_unlimited_context_usd_observed_cache": round(warm, 6),
        "hypothetical_unlimited_context_usd_no_cache": round(cold, 6),
    }


def measure_offline(output_dir=None):
    dataset = load_dev_scenarios()  # Validates the ORIGINAL catalog pin first.
    source = json.loads(DEFAULT_CATALOG_PATH.read_text())
    protected = reserved_names(dataset)
    encoder = tiktoken.encoding_for_model("gpt-4o")
    profiles = profiles_from_saved_logs()
    directory = Path(output_dir or BACKEND / "logs/evals" / f"scaling-{EXPANDER_VERSION}-seed{SEED}-{INDEX_VERSION}")
    directory.mkdir(parents=True, exist_ok=True)
    source_agent_bytes = (BACKEND / "agents/catalog_scheduler.json").read_bytes()
    config = json.loads(source_agent_bytes)
    index_text = index_message(config)["content"].partition(INDEX_MARKER)[2].strip()
    frozen_index_fields = tuple(json.loads(index_text)[0])
    if json.loads(index_text) != [{key: item[key] for key in frozen_index_fields} for item in source["appointment_types"]]:
        raise ValueError("Frozen type index differs from the pinned original catalog")
    if frozen_index_fields != INDEX_FIELDS:
        raise ValueError("Experiment index must use exactly the frozen index fields")
    original_index_tokens = len(encoder.encode(index_text))
    search_config = search_only_agent(config)
    (directory / "agent-search-only-exploratory.json").write_text(json.dumps(search_config, indent=2) + "\n")
    search_task_delta = sum(len(encoder.encode(m["content"])) for n in search_config["nodes"] for m in n["task_messages"]) - sum(
        len(encoder.encode(m["content"])) for n in config["nodes"] for m in n["task_messages"])
    measurements = {}

    def measure(factor):
        if factor in measurements:
            return measurements[factor]
        document = expand_catalog(source, factor, reserved_names=protected)
        catalog_path = directory / f"catalog-x{factor:02d}.json"
        catalog_path.write_bytes(canonical_bytes(document))
        catalog = load_catalog(catalog_path)  # Frozen loader validates all relations/hours.
        rendered = render_catalog(catalog)
        catalog_tokens = len(encoder.encode(rendered))
        index = render_type_index(document)
        agent = experiment_agent(config, document)
        agent_bytes = (json.dumps(agent, indent=2, ensure_ascii=False) + "\n").encode()
        # Validate experiment copies with the existing schema, without starting an agent.
        from agent_store import AgentStore
        AgentStore.validate(agent)
        manifest = expansion_manifest(source, document, factor)
        manifest.update(base_git_blob_sha=git_blob_sha(DEFAULT_CATALOG_PATH),
                        scenarios_sha256=sha256(DEFAULT_SCENARIOS_PATH.read_bytes()).hexdigest(),
                        expander_source_sha256=sha256(Path(__file__).with_name("catalog_expander.py").read_bytes()).hexdigest(),
                        index_version=INDEX_VERSION, index_fields=list(INDEX_FIELDS),
                        source_agent_sha256=sha256(source_agent_bytes).hexdigest(),
                        experiment_agent_sha256=sha256(agent_bytes).hexdigest(),
                        index_sha256=sha256(index.encode()).hexdigest(),
                        agent_changes="appointment index data only; instructions/tools/model/edges unchanged")
        (directory / f"catalog-x{factor:02d}.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (directory / f"catalog-x{factor:02d}.baseline.md").write_text(rendered)
        (directory / f"catalog-x{factor:02d}.type-index.json").write_text(index + "\n")
        (directory / f"agent-x{factor:02d}-expanded-index.json").write_bytes(agent_bytes)
        result = {
            "factor": factor, "catalog_tokens": catalog_tokens, "rendered_bytes": len(rendered.encode()),
            "complete_proposed_type_index_tokens": len(encoder.encode(index)),
            "counts": {key: len(document[key]) for key in COLLECTIONS},
            "catalog_alone_exceeds_context": catalog_tokens > CONTEXT_LIMIT,
            "manifest": manifest,
        }
        measurements[factor] = result
        return result

    base = measure(1)
    for factor in (5, 10, 20, 50):
        measure(factor)

    def first_factor_exceeding(predicate):
        low, high = 1, 50
        if not predicate(measure(high)):
            return None
        while low + 1 < high:
            mid = (low + high) // 2
            if predicate(measure(mid)):
                high = mid
            else:
                low = mid
        measure(high - 1)
        return high

    catalog_overflow = first_factor_exceeding(lambda m: m["catalog_tokens"] > CONTEXT_LIMIT)
    history_overflow = first_factor_exceeding(lambda m: profiles["baseline"]["max_prompt_tokens"]
                                              + m["catalog_tokens"] - base["catalog_tokens"] + OUTPUT_RESERVE > CONTEXT_LIMIT)
    for factor, measurement in measurements.items():
        measurement["baseline_one_run_each_projection"] = project(
            profiles["baseline"], measurement["catalog_tokens"] - base["catalog_tokens"], 1)
        measurement["baseline_initial_input_tokens_projection"] = (profiles["baseline"]["max_startup_prompt_tokens"]
                                                                   + measurement["catalog_tokens"] - base["catalog_tokens"])
    phases = []
    for arm, factor, repetitions in (("proposed-indexed", 5, 2), ("baseline", 5, 2),
                                     ("proposed-indexed", 10, 1), ("exploratory-search-only", 10, 1),
                                     ("exploratory-search-only", 50, 1)):
        m = measure(factor)
        profile = profiles["baseline" if arm == "baseline" else "proposed-v2"]
        delta = (m["catalog_tokens"] - base["catalog_tokens"] if arm == "baseline" else
                 m["complete_proposed_type_index_tokens"] - original_index_tokens)
        if arm == "exploratory-search-only":
            delta = search_task_delta
            # No search-only paid history exists: allow two extra model calls per
            # conversation, holding mean per-call usage/cache share constant.
            multiplier = (profile["model_calls"] + 2 * 12) / profile["model_calls"]
            profile = {**profile, **{key: profile[key] * multiplier for key in
                ("model_calls", "prompt_tokens", "cached_tokens", "completion_tokens")}}
        phases.append({"arm": arm, "factor": factor, "repetitions": repetitions,
                       **project(profile, delta, repetitions)})
    plans = {"revised_6b": {"phases": phases,
        "projected_usd_observed_cache": round(sum(p["projected_usd_with_observed_cache_share"] for p in phases), 6),
        "projected_usd_no_cache": round(sum(p["projected_usd_with_no_cache"] for p in phases), 6)}}
    indexed_x50 = project(profiles["proposed-v2"], measure(50)["complete_proposed_type_index_tokens"] - original_index_tokens, 1)
    report = {
        "expander_version": EXPANDER_VERSION, "index_version": INDEX_VERSION,
        "index_fields": list(INDEX_FIELDS), "frozen_index_fields": list(frozen_index_fields),
        "seed": SEED, "model": "gpt-4o", "tokenizer": encoder.name,
        "model_context_limit": CONTEXT_LIMIT, "output_reserve": OUTPUT_RESERVE, "network_calls": 0,
        "source_catalog_blob_sha": git_blob_sha(DEFAULT_CATALOG_PATH),
        "original_proposed_type_index_tokens": original_index_tokens,
        "first_integer_factor_catalog_alone_exceeds_context": catalog_overflow,
        "first_integer_factor_observed_history_projection_exceeds_context": history_overflow,
        "measurements": [measurements[k] for k in sorted(measurements)], "profiles": profiles, "plans": plans,
        "indexed_x50_projection_only": indexed_x50,
        "search_only_task_tokens_delta": search_task_delta,
        "prices": {"as_of": PRICE_DATE, "verified_on": "2026-11-10", "per_million_usd": PRICE_PER_MILLION,
                   "pricing_source": "https://developers.openai.com/api/docs/models/gpt-4o",
                   "cache_source": "https://developers.openai.com/api/docs/guides/prompt-caching"},
        "limitations": ["Catalog token sizes are measured offline. Model calls, full request sizes and dollars at expanded sizes are projections only.",
                        "Synthetic records are disconnected, irrelevant research-service distractors. No harder clinical near-neighbor test is claimed.",
                        "Original source agent, fixtures, outcomes, policy/core, instructions/tools and scorer remain unchanged. Derived copies replace only index data, as authorized. Original blob pin is checked; derived catalogs have separate manifests.",
                        "Indexed copies use exactly the frozen id+name format. No frozen-82 secondary arm. Indexed x50 is projection only.",
                        "Search-only is exploratory: index and its access sentence are replaced, resolve_options accepts free-text catalog queries rather than IDs; all other instructions/guards/tools are shared.",
                        "Search-only has no measured call-count profile: two extra calls per conversation are included; schema shrinkage is not credited. Larger search results and recoveries remain unmeasured.",
                        "Projections hold the prior call/history/output shape and cache fraction constant, plus one cold-scale-prefix premium. They are not spend ceilings or latency/pass-rate predictions.",
                        "Python lookup cost and invalid-filter valid-value lists can grow even when ordinary tool responses remain unchanged.",
                        "New-scale actual cache reads and total costs are unknown until authorized paid runs. GPT-4o does not separately expose cache-write tokens; their cost is included in uncached input, with zero additional write fee."],
    }
    path = directory / "offline-measurements.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return report, path


if __name__ == "__main__":
    report, path = measure_offline()
    print(json.dumps({"report": str(path), "measurements": [{k: m[k] for k in
        ("factor", "catalog_tokens", "complete_proposed_type_index_tokens", "counts")} for m in report["measurements"]],
        "catalog_overflow_factor": report["first_integer_factor_catalog_alone_exceeds_context"],
        "history_projection_overflow_factor": report["first_integer_factor_observed_history_projection_exceeds_context"],
        "plans": report["plans"]}, indent=2))
