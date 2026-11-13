import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ArrowRightIcon, BranchIcon, ChevronIcon, NodeIcon, PlusIcon, SettingsIcon, TrashIcon } from './icons.jsx'

// ---- Section open state, remembered per section in this browser -------------
const SECTIONS_KEY = 'agent-editor.sections'
let sectionState = (() => {
  try { return JSON.parse(localStorage.getItem(SECTIONS_KEY)) || {} } catch { return {} }
})()
function rememberSection(id, open) {
  sectionState = { ...sectionState, [id]: open }
  try { localStorage.setItem(SECTIONS_KEY, JSON.stringify(sectionState)) } catch { /* private mode: not remembered */ }
}
function useSectionOpen(id) {
  const [open, setOpen] = useState(sectionState[id] !== false)
  const set = (value) => { setOpen(value); rememberSection(id, value) }
  return [open, set]
}

// Grows with its content up to a cap. With `clampLines`, a collapsed textarea
// shows that many lines and reports whether its content is longer.
export function AutoTextarea({ value, minRows = 2, clampLines, collapsed = false, onLongChange, className = '', ...props }) {
  const ref = useRef(null)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    element.style.height = 'auto'
    const full = element.scrollHeight + 2
    let cap = 520
    if (clampLines) {
      const style = getComputedStyle(element)
      const clamp = parseFloat(style.lineHeight) * clampLines + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + 2
      onLongChange?.(full > clamp + 1)
      if (collapsed) cap = Math.min(cap, clamp)
    }
    element.style.height = `${Math.min(full, cap)}px`
  }, [value, collapsed, clampLines])
  return <textarea ref={ref} rows={minRows} value={value} className={`${className}${collapsed ? ' is-collapsed' : ''}`} {...props} />
}

// Space is always reserved so an error appearing never shifts the fields below.
function FieldError({ id, text }) {
  return <span id={id} className="field-error">{text || ''}</span>
}

function Section({ id, title, help, action, children }) {
  const [open, setOpen] = useSectionOpen(id)
  return <section className={`inspector-section${open ? '' : ' is-closed'}`} id={`section-${id}`} data-section={id}>
    <div className="inspector-section__head">
      <button type="button" className="section-toggle" aria-expanded={open} aria-controls={`section-body-${id}`} onClick={() => setOpen(!open)}>
        <ChevronIcon size={14} className="section-chevron" />
        <h3>{title}</h3>
      </button>
      {open && action}
    </div>
    {open && help && <p className="section-help">{help}</p>}
    {open && <div className="inspector-section__body" id={`section-body-${id}`}>{children}</div>}
  </section>
}

// Opens a section and brings it into view (used by the tools badge on a card).
// Each request applies once, so opening another step later does not jump again.
const handledReveals = new Set()
function useRevealSection(request, containerRef) {
  useEffect(() => {
    if (!request || handledReveals.has(request.nonce)) return
    handledReveals.add(request.nonce)
    rememberSection(request.section, true)
    const element = containerRef.current?.querySelector(`[data-section="${request.section}"]`)
    if (!element) return
    if (element.classList.contains('is-closed')) element.querySelector('.section-toggle')?.click()
    requestAnimationFrame(() => element.scrollIntoView({ block: 'start', behavior: 'smooth' }))
  }, [request?.nonce])
}

function Header({ icon, crumbs, title, subtitle }) {
  return <div className="inspector-header">
    <nav className="breadcrumb" aria-label="Inspector location">
      {crumbs.map((crumb, index) => <span key={index} className="breadcrumb__item">
        {index > 0 && <span className="breadcrumb__sep" aria-hidden="true">›</span>}
        {crumb.onClick
          ? <button type="button" className="breadcrumb__link" onClick={crumb.onClick}>{crumb.label}</button>
          : <span className="breadcrumb__current" aria-current="page">{crumb.label}</span>}
      </span>)}
    </nav>
    <div className="inspector-header__main">
      <span className="inspector-header__icon">{icon}</span>
      <div className="inspector-header__title">{title}</div>
    </div>
    {subtitle && <div className="inspector-header__subtitle">{subtitle}</div>}
  </div>
}

export function AgentInspector({ config, errors, onPatch, reveal }) {
  const ref = useRef(null)
  useRevealSection(reveal, ref)
  return <div className="inspector" ref={ref}>
    <Header icon={<SettingsIcon size={18} />} crumbs={[{ label: 'Agent' }]} title={config.name || 'Untitled agent'}
      subtitle="Click a step or a next-step label on the canvas to edit it." />
    <Section id="agent.name" title="Name">
      <label className="field">
        <span className="sr-only">Agent name</span>
        <input value={config.name} aria-invalid={Boolean(errors.name)} aria-describedby="err-agent-name"
          onChange={(event) => onPatch({ name: event.target.value })} />
        <FieldError id="err-agent-name" text={errors.name} />
      </label>
    </Section>
    <Section id="agent.instructions" title="Agent instructions" help="Applies to every step of the call.">
      <label className="field">
        <span className="sr-only">Agent instructions</span>
        <AutoTextarea minRows={4} value={config.persona || ''} onChange={(event) => onPatch({ persona: event.target.value })} />
      </label>
    </Section>
    <Section id="agent.first" title="First step" help="Where the call starts (the Start arrow).">
      <label className="field">
        <span className="sr-only">First step</span>
        <select value={config.initial_node} aria-invalid={Boolean(errors.initial_node)} aria-describedby="err-initial-node"
          onChange={(event) => onPatch({ initial_node: event.target.value })}>
          {!config.nodes.some((item) => item.name === config.initial_node) && <option value={config.initial_node}>{config.initial_node} (missing)</option>}
          {config.nodes.map((item) => <option key={item.name}>{item.name}</option>)}
        </select>
        <FieldError id="err-initial-node" text={errors.initial_node} />
      </label>
    </Section>
  </div>
}

const ROLE_LABELS = {
  developer: 'Instruction (developer)',
  system: 'Instruction (system)',
  user: 'Caller message (user)',
}

function MessageBlock({ message, index, onChange, onRemove }) {
  const [expanded, setExpanded] = useState(false)
  const [long, setLong] = useState(false)
  const [advanced, setAdvanced] = useState(message.role !== 'developer')
  const known = Object.keys(ROLE_LABELS).includes(message.role)
  return <div className={`message-block${message.role === 'user' ? ' is-caller' : ''}`}>
    <div className="message-block__bar">
      <span className="message-block__label">
        {message.role === 'user' ? 'Caller message' : 'Instruction'} {index + 1}
        {message.role !== 'developer' && <span className="role-tag">{message.role}</span>}
      </span>
      <button type="button" className="icon-btn" aria-label={`Remove instruction ${index + 1}`} title="Remove"
        onClick={onRemove}><TrashIcon size={15} /></button>
    </div>
    <AutoTextarea
      aria-label={`Instruction ${index + 1}`}
      minRows={3}
      clampLines={4}
      collapsed={!expanded}
      onLongChange={setLong}
      value={message.content}
      onFocus={() => setExpanded(true)}
      onChange={(event) => onChange({ content: event.target.value })}
    />
    <div className="message-block__foot">
      {long ? <button type="button" className="text-btn" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        {expanded ? 'Show less' : 'Show more'}
      </button> : <span />}
      <button type="button" className="text-btn subtle" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>
        <ChevronIcon size={12} className={`inline-chevron${advanced ? ' is-open' : ''}`} />Advanced
      </button>
    </div>
    {advanced && <div className="message-block__advanced">
      <label className="field">
        <span className="field-label">Message type</span>
        <select value={message.role} onChange={(event) => onChange({ role: event.target.value })}>
          {!known && <option value={message.role}>{message.role}</option>}
          {Object.entries(ROLE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
    </div>}
    {message.role === 'user' && <p className="role-warning" role="note">This text is sent as if the caller said it.</p>}
  </div>
}

export function NodeInspector({ node, nodes, tools, errors, isInitial, reveal, onPatch, onRename, onDelete, onOpenEdge, onAddEdge, onOpenAgent }) {
  const ref = useRef(null)
  useRevealSection(reveal, ref)
  const [name, setName] = useState(node.name)
  const clean = name.trim()
  const nameError = !clean ? 'Step name is required.'
    : clean !== node.name && nodes.some((item) => item.name === clean) ? 'Another step already has this name.'
      : errors.name
  const updateMessage = (index, patch) => onPatch({
    task_messages: node.task_messages.map((message, i) => i === index ? { ...message, ...patch } : message),
  })
  const hasExplicitPostActions = node.post_actions?.length > 0

  return <div className="inspector" ref={ref}>
    <Header icon={<NodeIcon size={18} />}
      crumbs={[{ label: 'Agent', onClick: () => onOpenAgent() }, { label: node.name }]}
      title={node.name}
      subtitle={isInitial ? 'First step of the call.' : null} />
    <Section id="node.name" title="Name">
      <label className="field">
        <span className="sr-only">Step name</span>
        <input value={name} aria-invalid={Boolean(nameError)} aria-describedby="err-node-name"
          onChange={(event) => setName(event.target.value)}
          onBlur={() => onRename(name)}
          onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} />
        <FieldError id="err-node-name" text={nameError && (clean !== node.name ? `${nameError} The rename is not applied until this is fixed.` : nameError)} />
      </label>
    </Section>

    <Section id="node.instructions" title="Step instructions" help="What the agent must do in this step."
      action={<button type="button" className="btn btn-sm btn-ghost"
        onClick={() => onPatch({ task_messages: [...node.task_messages, { role: 'developer', content: '' }] })}><PlusIcon size={14} />Add</button>}>
      {node.task_messages.length === 0 && <p className="empty-note">No instructions yet. Add one to tell the agent what to do here.</p>}
      {node.task_messages.map((message, index) => <MessageBlock key={index} message={message} index={index}
        onChange={(patch) => updateMessage(index, patch)}
        onRemove={() => onPatch({ task_messages: node.task_messages.filter((_, i) => i !== index) })} />)}
    </Section>

    <Section id="node.persona" title="Step persona (optional)"
      help={<>Replaces the <button type="button" className="inline-link" onClick={() => onOpenAgent('agent.instructions')}>agent instructions</button> for this step only. Leave empty to keep them.</>}>
      <label className="field">
        <span className="sr-only">Step persona</span>
        <AutoTextarea minRows={2} value={node.role_message || ''} placeholder="Empty: the agent instructions apply."
          onChange={(event) => onPatch({ role_message: event.target.value || null })} />
      </label>
    </Section>

    <Section id="node.tools" title={`Actions available in this step (${node.functions.length})`}
      help="Lookups and bookings the agent can run without leaving this step.">
      <div className="check-list">{tools.map((tool) => <label className="check" key={tool}>
        <input type="checkbox" checked={node.functions.includes(tool)} onChange={(event) => onPatch({
          functions: event.target.checked ? [...node.functions, tool] : node.functions.filter((item) => item !== tool),
        })} />
        <span className="mono">{tool}</span>
      </label>)}</div>
    </Section>

    <Section id="node.next" title="Next steps" help="When the agent moves on, and where."
      action={<button type="button" className="btn btn-sm btn-ghost" onClick={onAddEdge}><PlusIcon size={14} />Add</button>}>
      {node.edges.length === 0 && <p className="empty-note">No next steps. Drag from the bottom handle of this step to another step, or click Add.</p>}
      <div className="transition-list">{node.edges.map((edge, index) => {
        const invalid = Boolean(errors.edges[index])
        return <button type="button" key={index} className={`transition-row${invalid ? ' has-error' : ''}`} onClick={() => onOpenEdge(index)}>
          <BranchIcon size={15} />
          <span className="transition-row__text">{edge.description || edge.function || 'Untitled next step'}</span>
          <span className="transition-row__target"><ArrowRightIcon size={13} />{edge.target}</span>
        </button>
      })}</div>
    </Section>

    <Section id="node.ending" title="Ending">
      <label className="check">
        <input type="checkbox" checked={node.end} onChange={(event) => onPatch({ end: event.target.checked })} />
        <span>Ends the call <span className="field-help">The call ends after this step.</span></span>
      </label>
      <label className={`check${!node.end || hasExplicitPostActions ? ' is-disabled' : ''}`}>
        <input type="checkbox" checked={node.auto_end !== false} disabled={!node.end || hasExplicitPostActions}
          onChange={(event) => onPatch({ auto_end: event.target.checked })} />
        <span>Hang up automatically <span className="field-help">
          {hasExplicitPostActions ? 'Set by this step’s post actions.' : 'Off: no further steps, but the line stays open until the caller hangs up.'}
        </span></span>
      </label>
    </Section>

    <div className="inspector-footer">
      <button type="button" className="btn btn-danger-ghost" onClick={onDelete}><TrashIcon size={15} />Delete step</button>
    </div>
  </div>
}

export function EdgeInspector({ source, edge, index, nodes, errors, onPatch, onDelete, onOpenNode, onOpenAgent }) {
  const nodeNames = nodes.map((item) => item.name)
  return <div className="inspector">
    <Header icon={<BranchIcon size={18} />}
      crumbs={[{ label: 'Agent', onClick: () => onOpenAgent() }, { label: source.name, onClick: onOpenNode }, { label: edge.function || 'Next step' }]}
      title={<span className="route"><span>{source.name}</span><ArrowRightIcon size={14} /><span>{edge.target}</span></span>} />
    <Section id="edge.when" title="When to move on" help="The agent reads this to decide when to take this next step.">
      <label className="field">
        <span className="sr-only">When to move on</span>
        <AutoTextarea minRows={3} value={edge.description} onChange={(event) => onPatch({ description: event.target.value })} />
      </label>
    </Section>
    <Section id="edge.where" title="Where it goes">
      <div className="field">
        <span className="field-label">From</span>
        <button type="button" className="link-row" onClick={onOpenNode}><NodeIcon size={15} />{source.name}</button>
      </div>
      <label className="field">
        <span className="field-label">To</span>
        <select value={edge.target} aria-invalid={Boolean(errors.target)} aria-describedby={`err-edge-target-${index}`}
          onChange={(event) => onPatch({ target: event.target.value })}>
          {!nodeNames.includes(edge.target) && <option value={edge.target}>{edge.target} (missing)</option>}
          {nodes.map((item) => <option key={item.name}>{item.name}</option>)}
        </select>
        <FieldError id={`err-edge-target-${index}`} text={errors.target} />
      </label>
    </Section>
    <Section id="edge.function" title="Function name" help="The name the model calls to move on. Unique within the step.">
      <label className="field">
        <span className="sr-only">Function name</span>
        <input className="mono" value={edge.function} aria-invalid={Boolean(errors.function)} aria-describedby={`err-edge-fn-${index}`}
          onChange={(event) => onPatch({ function: event.target.value })} />
        <FieldError id={`err-edge-fn-${index}`} text={errors.function} />
      </label>
    </Section>
    <div className="inspector-footer">
      <button type="button" className="btn btn-danger-ghost" onClick={onDelete}><TrashIcon size={15} />Delete next step</button>
    </div>
  </div>
}
