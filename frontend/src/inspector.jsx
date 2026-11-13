import { useLayoutEffect, useRef, useState } from 'react'
import { ArrowRightIcon, BranchIcon, NodeIcon, PlusIcon, SettingsIcon, TrashIcon } from './icons.jsx'

// Grows with its content up to a cap, then scrolls.
export function AutoTextarea({ value, minRows = 2, ...props }) {
  const ref = useRef(null)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight + 2, 520)}px`
  }, [value])
  return <textarea ref={ref} rows={minRows} value={value} {...props} />
}

// Space is always reserved so an error appearing never shifts the fields below.
function FieldError({ id, text }) {
  return <span id={id} className="field-error">{text || ''}</span>
}

function Section({ title, action, children }) {
  return <section className="inspector-section">
    <div className="inspector-section__head"><h3>{title}</h3>{action}</div>
    {children}
  </section>
}

function Header({ icon, kind, title, subtitle }) {
  return <div className="inspector-header">
    <span className="inspector-header__icon">{icon}</span>
    <div>
      <div className="inspector-header__kind">{kind}</div>
      <div className="inspector-header__title">{title}</div>
      {subtitle && <div className="inspector-header__subtitle">{subtitle}</div>}
    </div>
  </div>
}

export function AgentInspector({ config, errors, onPatch }) {
  return <div className="inspector">
    <Header icon={<SettingsIcon size={18} />} kind="Agent settings" title={config.name || 'Untitled agent'}
      subtitle="Click a node or a transition on the canvas to edit it." />
    <Section title="Name">
      <label className="field">
        <span className="sr-only">Agent name</span>
        <input value={config.name} aria-invalid={Boolean(errors.name)} aria-describedby="err-agent-name"
          onChange={(event) => onPatch({ name: event.target.value })} />
        <FieldError id="err-agent-name" text={errors.name} />
      </label>
    </Section>
    <Section title="Persona">
      <label className="field">
        <span className="field-help">Default role message for every node that does not set its own.</span>
        <AutoTextarea minRows={4} value={config.persona || ''} onChange={(event) => onPatch({ persona: event.target.value })} />
      </label>
    </Section>
    <Section title="Start">
      <label className="field">
        <span className="field-help">The node every call starts in.</span>
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

export function NodeInspector({ node, nodes, tools, errors, isInitial, onPatch, onRename, onDelete, onOpenEdge, onAddEdge }) {
  const [name, setName] = useState(node.name)
  const clean = name.trim()
  const nameError = !clean ? 'Node name is required.'
    : clean !== node.name && nodes.some((item) => item.name === clean) ? 'Another node already has this name.'
      : errors.name
  const updateMessage = (index, patch) => onPatch({
    task_messages: node.task_messages.map((message, i) => i === index ? { ...message, ...patch } : message),
  })
  const hasExplicitPostActions = node.post_actions?.length > 0

  return <div className="inspector">
    <Header icon={<NodeIcon size={18} />} kind={isInitial ? 'Initial node' : 'Node'} title={node.name} />
    <Section title="Name">
      <label className="field">
        <span className="sr-only">Node name</span>
        <input value={name} aria-invalid={Boolean(nameError)} aria-describedby="err-node-name"
          onChange={(event) => setName(event.target.value)}
          onBlur={() => onRename(name)}
          onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} />
        <FieldError id="err-node-name" text={nameError && (clean !== node.name ? `${nameError} The rename is not applied until this is fixed.` : nameError)} />
      </label>
    </Section>

    <Section title="Task messages" action={<button type="button" className="btn btn-sm btn-ghost"
      onClick={() => onPatch({ task_messages: [...node.task_messages, { role: 'developer', content: '' }] })}><PlusIcon size={14} />Add</button>}>
      {node.task_messages.length === 0 && <p className="empty-note">No task messages. Add one to tell the agent what to do in this node.</p>}
      {node.task_messages.map((message, index) => <div className="message-block" key={index}>
        <div className="message-block__bar">
          <select aria-label={`Role of message ${index + 1}`} value={message.role} onChange={(event) => updateMessage(index, { role: event.target.value })}>
            <option value="developer">developer</option><option value="system">system</option><option value="user">user</option>
          </select>
          <button type="button" className="icon-btn" aria-label={`Remove message ${index + 1}`} title="Remove message"
            onClick={() => onPatch({ task_messages: node.task_messages.filter((_, i) => i !== index) })}><TrashIcon size={15} /></button>
        </div>
        <AutoTextarea aria-label={`Message ${index + 1} content`} minRows={3} value={message.content}
          onChange={(event) => updateMessage(index, { content: event.target.value })} />
      </div>)}
    </Section>

    <Section title="Role message">
      <label className="field">
        <span className="field-help">Leave empty to use the agent persona.</span>
        <AutoTextarea minRows={2} value={node.role_message || ''} onChange={(event) => onPatch({ role_message: event.target.value || null })} />
      </label>
    </Section>

    <Section title={`Tools (${node.functions.length})`}>
      <div className="check-list">{tools.map((tool) => <label className="check" key={tool}>
        <input type="checkbox" checked={node.functions.includes(tool)} onChange={(event) => onPatch({
          functions: event.target.checked ? [...node.functions, tool] : node.functions.filter((item) => item !== tool),
        })} />
        <span className="mono">{tool}</span>
      </label>)}</div>
    </Section>

    <Section title="Transitions" action={<button type="button" className="btn btn-sm btn-ghost" onClick={onAddEdge}><PlusIcon size={14} />Add</button>}>
      {node.edges.length === 0 && <p className="empty-note">No transitions. Drag from the bottom handle of this node to another node, or click Add.</p>}
      <div className="transition-list">{node.edges.map((edge, index) => {
        const invalid = Boolean(errors.edges[index])
        return <button type="button" key={index} className={`transition-row${invalid ? ' has-error' : ''}`} onClick={() => onOpenEdge(index)}>
          <BranchIcon size={15} />
          <span className="transition-row__text">{edge.description || edge.function || 'Untitled transition'}</span>
          <span className="transition-row__target"><ArrowRightIcon size={13} />{edge.target}</span>
        </button>
      })}</div>
    </Section>

    <Section title="Ending">
      <label className="check">
        <input type="checkbox" checked={node.end} onChange={(event) => onPatch({ end: event.target.checked })} />
        <span>Terminal node <span className="field-help">Leads to End on the canvas.</span></span>
      </label>
      <label className={`check${!node.end || hasExplicitPostActions ? ' is-disabled' : ''}`}>
        <input type="checkbox" checked={node.auto_end !== false} disabled={!node.end || hasExplicitPostActions}
          onChange={(event) => onPatch({ auto_end: event.target.checked })} />
        <span>Hang up automatically <span className="field-help">
          {hasExplicitPostActions ? 'Set by this node’s post actions.' : 'Off: the call stays open until the caller hangs up.'}
        </span></span>
      </label>
    </Section>

    <div className="inspector-footer">
      <button type="button" className="btn btn-danger-ghost" onClick={onDelete}><TrashIcon size={15} />Delete node</button>
    </div>
  </div>
}

export function EdgeInspector({ source, edge, index, nodes, errors, onPatch, onDelete, onOpenNode }) {
  const nodeNames = nodes.map((item) => item.name)
  return <div className="inspector">
    <Header icon={<BranchIcon size={18} />} kind="Transition"
      title={<span className="route"><span>{source.name}</span><ArrowRightIcon size={14} /><span>{edge.target}</span></span>} />
    <Section title="Description">
      <label className="field">
        <span className="field-help">When should the agent take this transition? The model reads this text.</span>
        <AutoTextarea minRows={3} value={edge.description} onChange={(event) => onPatch({ description: event.target.value })} />
      </label>
    </Section>
    <Section title="Function name">
      <label className="field">
        <span className="field-help">The function the model calls. Unique within the node.</span>
        <input className="mono" value={edge.function} aria-invalid={Boolean(errors.function)} aria-describedby={`err-edge-fn-${index}`}
          onChange={(event) => onPatch({ function: event.target.value })} />
        <FieldError id={`err-edge-fn-${index}`} text={errors.function} />
      </label>
    </Section>
    <Section title="Route">
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
    <div className="inspector-footer">
      <button type="button" className="btn btn-danger-ghost" onClick={onDelete}><TrashIcon size={15} />Delete transition</button>
    </div>
  </div>
}
