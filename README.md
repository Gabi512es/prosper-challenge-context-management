# Prosper: catalog-aware voice scheduling

This submission includes a visual agent editor and a browser test-call workflow
for a scheduler backed by a synthetic clinic catalog. It clarifies requests,
explains catalog restrictions and records simulated appointments after confirmation.
[solution.md](solution.md) explains the design, its evolution and the measured comparison.

## Run locally

Requires Python 3.11+, Node.js 20 or a newer LTS release, and npm.
On macOS: `brew install python@3.11 node`. From the repository root:

```sh
make install
cp backend/.env.example backend/.env
```

Fill in `OPENAI_API_KEY` and `ELEVENLABS_API_KEY` in `backend/.env`, which is
Git-ignored. These are the only required environment variables; never commit keys.

```sh
make test                 # offline tests; paid integrations are disabled
make run                  # terminal 1: voice service on port 7860
```

In a second terminal, from the same repository:

```sh
make editor               # editor on port 5173; API on port 8000
```

Open **http://localhost:5173**, select **Scheduler v4**, and click **Test call**.
This saves the agent and selects it for the next connection. Open the Pipecat
client at **http://localhost:7860/client/** if the new tab is blocked, click
**Connect**, and allow microphone access. Disconnect when finished; Ctrl+C stops
each service. Voice calls use paid services.

## What you can edit

- **Scheduler v4**, the sole bundled agent and default: edit its greeting, voice
  and per-step clinic guidance. Its scheduling steps, read-backs and consent
  checks are fixed in code.
- **Generic Flows agents**: click **New**, enter a name, and click **Create agent**.
  Select the `start` node, edit **Step instructions**, and **Save**. These graphs
  also support editing nodes, attached tools and transitions. Select Scheduler v4
  again before trying the booking example.

The saved JSON's `runtime` field chooses the execution path. Scheduler v4 uses
structured model interpretation followed by code-controlled state and replies.
Its internal prompt/schema version is **v1.10**, with **gpt-4o-2024-08-06** pinned.
A generic Flows agent uses model/tool orchestration instead. Selection is local
and shared across tabs; Test call reloads saved JSON on the next connection.

## Try it

**Booking:** “I'd like an annual physical with Maria Garcia, the Family Medicine
one. I'm a new patient.” Choose Midtown, provide the synthetic identity **Alex Morgan,
April 12, 1990**, confirm the correct identity read-back, choose an offered time,
and say yes after the full booking read-back. This Maria Garcia is a nurse
practitioner, distinct from the pediatrician with the same name.

**Policy:** “I'm an existing patient with a referral on file. I'd like a knee MRI
with Linda Ramirez in Radiology at Mission Bay.” Mission Bay lacks imaging, so the
agent should explain the restriction and offer an eligible site.

Availability and bookings are simulated; no real appointment, transfer or callback
is created. Local, ignored `backend/logs/` may contain the supplied name and date of birth.
