# Voice findings: live test calls, November 8 to 12

Live voice calls placed and judged by the author through the Pipecat browser
client (ElevenLabs speech-to-text and text-to-speech, gpt-4o). Each line is
taken from the author's own call logs, which are not saved in the repository.
Implementation details of each fix are in docs/decisions.md.

**What the text evaluations did not see:** the scripted patients never
interrupt, never mishear or get misheard, never ask a side question in the
middle of a choice and never wait in silence, so timing, speech recognition
and turn-taking defects only appeared in live calls.

| Date | What happened | Cause found | Fix | Source |
|---|---|---|---|---|
| Nov 8 | The agent promised "clinic staff will follow up" and offered a transfer nobody asked for. | No callback or transfer exists in the prototype; the handoff instructions still described staff follow-up. | No promises: the agent gives the clinic phone number only. | author's voice call logs, not saved in the repository |
| Nov 8 | When no slot matched, the agent stopped without offering alternatives. | No alternative search existed. | Deterministic alternatives, one constraint relaxed at a time, offered only with the patient's consent. | author's voice call logs, not saved in the repository |
| Nov 8 | Voice calls only had the evaluation fixture slots. | Voice and evaluations shared the same small fixture availability. | Seeded demo availability for voice, covering 760 combinations. | author's voice call logs, not saved in the repository |
| Nov 8 | The agent spoke twice in a row. | Parallel tool calls, plus a separate silent-cutoff recovery speaker. | Parallel tool calls turned off; recovery speaker removed. | author's voice call logs, not saved in the repository |
| Nov 8 | The author asked for Midtown and the agent booked North Beach. | The model passed a location ID directly, overriding the spoken site. | The spoken location takes precedence; the agent asks when the two conflict. | author's voice call logs, not saved in the repository |
| Nov 8 and 9 | A misheard date of birth (1992, 1994) went unnoticed inside a long read-back. | Identity was only read back inside the full booking read-back, where an error is easy to miss. | Short identity confirmation as soon as name and date of birth are given. | author's voice call logs, not saved in the repository |
| Nov 9 | The consent gate refused valid "yes" replies and the booking failed. | An interruption cancelled the consent even for a plain "yeah", and the agent then sent the caller to the clinic instead of asking again; in a second call, slots the model had listed in its own words were not registered as offered (slot_not_offered). | Two-phase booking: read-back first, then booking only after a later yes. | author's voice call logs, not saved in the repository |
| Nov 9 | "Linda Ramirez in radiology" was not found. | The specialty parser matched "ENT" inside the word "patient". | Whole-term specialty matching. | author's voice call logs, not saved in the repository |
| Nov 9 | After "nearest clinic geographically", the agent asked the same clarification three times. | The request was handled by parsing keywords in the transcript. | A closed field (time, place or unclear) filled by the model and validated in code. | author's voice call logs, not saved in the repository |
| Nov 9 | The model invented a "primary care" specialty filter that removed every candidate provider. | Code applied a free-text filter from the model without checking it against the catalog. | Runtime validation of filters against the catalog. | author's voice call logs, not saved in the repository |
| Nov 9 | After the author said "1991.", the agent stayed silent for 12 seconds. | "1991." was not counted as a real word, so the turn was dropped. | Numbers and dates count as words. | author's voice call logs, not saved in the repository |
| Nov 9 | **Voice call A passed:** soonest search, identity read-back, a single offer, booking and recap. | n/a | n/a | author's voice call logs, not saved in the repository |
| Nov 12 | After an interruption during a slot choice, the agent repeated "Your details are confirmed. I'll check the available appointments." five times without calling any tool. | The pending slot choice was lost after the interruption, and a canned line filled the gap. | Durable slot-choice stage; canned line removed. | author's voice call logs, not saved in the repository |
| Nov 12 | After "Sorry, what did you say?", the agent presented the slots twice. | The model's own offer and the code's repeated choice were both spoken. | Repeat requests answered once, with the choice and its context. | author's voice call logs, not saved in the repository |
| Nov 12 | **Final call worked:** interruption handled, choice repeated once, booking and short recap. | n/a | n/a | author's voice call logs, not saved in the repository |

Where the call logs record the symptom but not the cause (the alternatives,
fixture-only availability and date-of-birth rows), the "Cause found"
entry summarizes the matching investigation in docs/decisions.md.

The November 12 fixes belong to v2.1 (see docs/decisions.md, 2026-11-12). They
were verified by these calls, offline tests and one four-case text smoke, not by
a full evaluation matrix.
