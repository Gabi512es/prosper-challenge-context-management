// Plain-English wording for the fixed v4 steps, for a non-technical reader. The
// step ids and transitions themselves are fixed in backend/v4/agent_config.py;
// anything not listed here falls back to the id and the file's own description.
export const STEP_TEXT = {
  collect_request: {
    title: 'Request',
    does: 'The agent finds out which service, provider and site the caller wants, and answers questions about the clinic along the way.',
  },
  identity: {
    title: 'Identity check',
    does: "The agent asks for the caller's name and date of birth, then reads them back.",
  },
  choose_slot: {
    title: 'Choose a time',
    does: 'The agent offers up to three available times and the caller picks one.',
  },
  confirm_booking: {
    title: 'Confirm',
    does: 'The agent reads the booking back and books it only after the caller clearly says yes.',
  },
  booked: {
    title: 'Booked',
    does: 'The agent confirms the booking, then asks whether the caller needs anything else.',
  },
  human_handoff: {
    title: 'Asks for a person',
    does: "The agent explains that it cannot transfer the call and gives the clinic's phone number.",
  },
  emergency: {
    title: 'Emergency',
    does: 'The agent tells the caller to call emergency services right away and gives no medical advice.',
  },
}

// "When …" for each fixed transition, keyed by step id and transition function.
const WHEN = {
  'collect_request:request_complete': 'When the service, provider and site are all known',
  'identity:identity_confirmed': 'When the caller confirms their name and date of birth',
  'identity:cancel_request': 'When the caller cancels the request (the call goes on)',
  'choose_slot:slot_chosen': 'When the caller picks one of the offered times',
  'choose_slot:change_request': 'When the caller changes the service, provider, site or date',
  'confirm_booking:caller_accepts': 'When the caller clearly says yes, the appointment is booked',
  'confirm_booking:caller_changes': 'When the caller says no, asks a question or changes something',
  'booked:another_request': 'When the caller asks for something else',
}

export const stepTitle = (name) => STEP_TEXT[name]?.title || name
export const stepDoes = (node) => STEP_TEXT[node.name]?.does || node.description || ''

// The step's next steps as plain sentences.
export function nextStepSentences(node, anyTime) {
  const sentences = node.edges.map((edge) => {
    const when = WHEN[`${node.name}:${edge.function}`] || `When ${(edge.description || '').replace(/\.$/, '').replace(/^\w/, (c) => c.toLowerCase())}`
    const back = Object.keys(STEP_TEXT).indexOf(edge.target) < Object.keys(STEP_TEXT).indexOf(node.name)
    return `${when}, go ${back ? 'back ' : ''}to ${stepTitle(edge.target)}.`
  })
  if (anyTime) sentences.unshift('This can happen at any point of the call.')
  if (node.end) sentences.push(node.edges.length ? 'Otherwise, the call ends.' : 'Then the call ends.')
  return sentences
}
