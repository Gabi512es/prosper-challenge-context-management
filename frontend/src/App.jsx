import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Background, MarkerType, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { CanvasControls, edgeTypes, nodeTypes } from './canvas.jsx'
import { ConfirmDialog, NameDialog } from './dialogs.jsx'
import { AgentInspector, EdgeInspector, NodeInspector } from './inspector.jsx'
import { PhoneIcon, PlusIcon } from './icons.jsx'
import { END_ID, START_ID, autoLayout, endsCall, estimateHeight, virtualPositions } from './layout.js'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (response.status === 204) return null
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = payload.detail || payload
    const errors = detail.errors || [detail.message || `Request failed (${response.status})`]
    const error = new Error(errors.join('\n'))
    error.errors = errors
    throw error
  }
  return payload
}

const blankEdge = (target, index) => ({
  function: `transition_${index + 1}`,
  description: 'Describe when the assistant should take this transition.',
  target,
  properties: {},
  required: [],
})

// Field-level checks shown next to the field they concern. The server still
// runs the full AgentBuilder validation on save; these catch the common cases
// early and point at the exact input.
function validateConfig(config, tools) {
  const result = { agent: {}, nodes: {}, count: 0 }
  if (!config) return result
  const add = (target, key, text) => { target[key] = text; result.count += 1 }
  if (!config.name?.trim()) add(result.agent, 'name', 'Agent name is required.')
  const names = config.nodes.map((node) => node.name)
  if (!names.includes(config.initial_node)) {
    add(result.agent, 'initial_node', `Initial node "${config.initial_node}" does not exist.`)
  }
  config.nodes.forEach((node, nodeIndex) => {
    const errors = { edges: {} }
    if (!node.name?.trim()) add(errors, 'name', 'Node name is required.')
    else if (names.filter((name) => name === node.name).length > 1) add(errors, 'name', 'Node names must be unique.')
    const seen = new Set()
    node.edges.forEach((edge, edgeIndex) => {
      const edgeErrors = {}
      const fn = edge.function?.trim()
      if (!fn) add(edgeErrors, 'function', 'Function name is required.')
      else if (seen.has(fn)) add(edgeErrors, 'function', 'Function names must be unique within a node.')
      else if (tools.includes(fn) && node.functions.includes(fn)) add(edgeErrors, 'function', 'This name is already used by an attached tool.')
      if (fn) seen.add(fn)
      if (!names.includes(edge.target)) add(edgeErrors, 'target', `Target node "${edge.target}" does not exist.`)
      if (Object.keys(edgeErrors).length) errors.edges[edgeIndex] = edgeErrors
    })
    if (errors.name || Object.keys(errors.edges).length) result.nodes[nodeIndex] = errors
  })
  return result
}

function ActionButton({ loading = false, className = '', disabled, children, ...props }) {
  return <button
    type="button"
    className={`btn ${className} ${loading ? 'is-loading' : ''}`}
    disabled={disabled || loading}
    aria-busy={loading || undefined}
    {...props}
  >
    <span className="btn-spinner" aria-hidden="true" />
    {children}
  </button>
}

const AGENT = { kind: 'agent' }
const EDGE_COLOR = '#c9c9c6'
const EDGE_ACTIVE = '#1f1f1f'
const EDGE_ERROR = '#c2362b'

export default function App() {
  const [agents, setAgents] = useState([])
  const [agentId, setAgentId] = useState('')
  const [config, setConfig] = useState(null)
  const [savedSnapshot, setSavedSnapshot] = useState('')
  // What the inspector shows: the agent, a node (by name) or an edge (source name + index).
  const [selection, setSelection] = useState(AGENT)
  const [positions, setPositions] = useState({})
  const [tools, setTools] = useState([])
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState({ kind: 'info', text: 'Loading agents…' })
  const [serverErrors, setServerErrors] = useState([])
  const [dialog, setDialog] = useState(null)
  const positionsRef = useRef(positions)
  positionsRef.current = positions
  // Sizes React Flow measured. Passed back on every render: node objects are
  // rebuilt on each edit, and a node without `measured` is hidden until it is
  // measured again, which made nodes flicker and swallowed double-clicks.
  const measuredRef = useRef({})

  const dirty = Boolean(config) && JSON.stringify(config) !== savedSnapshot
  const validation = useMemo(() => validateConfig(config, tools), [config, tools])
  const locked = Boolean(busy)

  useEffect(() => {
    if (!dirty) return undefined
    // The browser's own leave-page prompt is the only option when closing the tab.
    const warn = (event) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  // In-app replacement for window.confirm/prompt: resolves with the dialog result.
  const ask = (spec) => new Promise((resolve) => setDialog({ ...spec, resolve }))
  const closeDialog = (value) => { dialog?.resolve(value); setDialog(null) }

  const showError = (error, prefix) => {
    const errors = error.errors || [error.message]
    setServerErrors(errors)
    setMessage({ kind: 'error', text: prefix ? `${prefix}: ${errors[0]}` : errors[0] })
  }

  const confirmDiscard = async () => !dirty || ask({
    kind: 'confirm',
    title: 'Discard unsaved changes?',
    body: <>Your changes to <strong>{config.name || agentId}</strong> have not been saved.</>,
    confirmLabel: 'Discard changes',
    danger: true,
  })

  const loadAgent = async (id, { force = false } = {}) => {
    if (!force && id === agentId) return
    if (!force && !(await confirmDiscard())) return
    setBusy('load')
    try {
      const [payload, layout] = await Promise.all([
        request(`/api/agents/${id}`),
        request(`/api/agents/${id}/layout`).catch(() => ({ positions: {} })),
      ])
      setAgentId(id)
      setConfig(payload.config)
      setSavedSnapshot(JSON.stringify(payload.config))
      setSelection(AGENT)
      setPositions(layout.positions || {})
      setServerErrors([])
      setMessage({ kind: 'info', text: `Loaded ${payload.config.name}` })
    } catch (error) {
      showError(error, 'Could not load the agent')
    } finally {
      setBusy('')
    }
  }

  const refreshAgents = async (preferred) => {
    const payload = await request('/api/agents')
    setAgents(payload.agents)
    const next = preferred || payload.active_agent_id || payload.agents[0]?.id
    if (next) await loadAgent(next, { force: true })
    else {
      setConfig(null)
      setAgentId('')
      setSavedSnapshot('')
    }
  }

  useEffect(() => {
    Promise.all([request('/api/agents'), request('/api/tools')])
      .then(([agentPayload, toolPayload]) => {
        setAgents(agentPayload.agents)
        setTools(toolPayload.tools)
        const id = agentPayload.active_agent_id || agentPayload.agents[0]?.id
        if (id) loadAgent(id, { force: true })
        else setMessage({ kind: 'info', text: 'Create an agent to begin.' })
      })
      .catch((error) => showError(error, 'Could not reach the editor API'))
  }, [])

  const persistLayout = async (id, layout) => {
    const names = new Set((config?.nodes || []).map((node) => node.name))
    const kept = Object.fromEntries(Object.entries(layout).filter(([name]) => names.has(name)))
    await request(`/api/agents/${id}/layout`, { method: 'PUT', body: JSON.stringify({ positions: kept }) })
  }

  const patchConfig = (patch) => setConfig((current) => ({ ...current, ...patch }))
  const patchNode = (name, patch) => setConfig((current) => ({
    ...current,
    nodes: current.nodes.map((node) => node.name === name ? { ...node, ...patch } : node),
  }))

  const renameNode = (oldName, newName) => {
    const clean = (newName || '').trim()
    if (clean === oldName) return true
    if (!clean || config.nodes.some((node) => node.name === clean)) return false
    setConfig((current) => ({
      ...current,
      initial_node: current.initial_node === oldName ? clean : current.initial_node,
      nodes: current.nodes.map((node) => ({
        ...node,
        name: node.name === oldName ? clean : node.name,
        edges: node.edges.map((edge) => ({
          ...edge,
          target: edge.target === oldName ? clean : edge.target,
        })),
      })),
    }))
    setPositions((current) => {
      if (!current[oldName]) return current
      const next = { ...current, [clean]: current[oldName] }
      delete next[oldName]
      return next
    })
    measuredRef.current[clean] = measuredRef.current[oldName]
    setSelection((current) => current.kind !== 'agent' && current.name === oldName ? { ...current, name: clean } : current)
    return true
  }

  // ---- Canvas model -------------------------------------------------------
  // Saved positions win; nodes without one are placed by the automatic layout.
  const structureKey = config ? JSON.stringify([config.initial_node, config.nodes.map((node) =>
    [node.name, node.end, node.functions.length, node.edges.map((edge) => edge.target)])]) : ''
  const fallback = useMemo(() => config ? autoLayout(config) : {}, [structureKey])
  // A layout file that covers only some nodes (older editor versions saved
  // positions node by node) is ignored in favour of a full automatic layout:
  // mixing the two overlaps nodes. Nothing is written until a drag or Tidy up.
  const layoutComplete = Boolean(config) && config.nodes.every((node) => positions[node.name])
  const placed = useMemo(() => {
    if (!config) return {}
    return Object.fromEntries(config.nodes.map((node) => [node.name,
      (layoutComplete && positions[node.name]) || fallback[node.name] || { x: 0, y: 0 }]))
  }, [config, positions, fallback, layoutComplete])
  const placedRef = useRef(placed)
  placedRef.current = placed
  const layoutCompleteRef = useRef(layoutComplete)
  layoutCompleteRef.current = layoutComplete
  const virtual = useMemo(() => config ? virtualPositions(config, placed, estimateHeight) : {}, [config, placed])

  const selectedNodeName = selection.kind === 'node' ? selection.name : null

  const graphNodes = useMemo(() => {
    if (!config) return []
    const items = config.nodes.map((node, index) => ({
      id: node.name,
      type: 'agent',
      position: placed[node.name],
      measured: measuredRef.current[node.name],
      data: {
        node,
        active: selectedNodeName === node.name,
        hasError: Boolean(validation.nodes[index]),
        onRename: (name) => renameNode(node.name, name),
      },
    }))
    if (virtual[START_ID]) items.push({ id: START_ID, type: 'start', position: virtual[START_ID], measured: measuredRef.current[START_ID], draggable: false, selectable: false, connectable: false, data: {} })
    if (virtual[END_ID]) items.push({ id: END_ID, type: 'end', position: virtual[END_ID], measured: measuredRef.current[END_ID], draggable: false, selectable: false, connectable: false, data: {} })
    return items
  }, [config, placed, virtual, selectedNodeName, validation])

  const graphEdges = useMemo(() => {
    if (!config) return []
    const marker = (color) => ({ type: MarkerType.Arrow, color, width: 18, height: 18, strokeWidth: 1.6 })
    const outgoing = {}
    const incoming = {}
    config.nodes.forEach((node) => node.edges.forEach((edge) => {
      outgoing[node.name] = (outgoing[node.name] || 0) + 1
      incoming[edge.target] = (incoming[edge.target] || 0) + 1
    }))
    const labelT = (source, target) => {
      const fansOut = outgoing[source] > 1
      const fansIn = incoming[target] > 1
      return fansOut && !fansIn ? 0.64 : fansIn && !fansOut ? 0.36 : 0.5
    }
    const items = config.nodes.flatMap((node, nodeIndex) => node.edges.map((edge, index) => {
      const active = selection.kind === 'edge' && selection.name === node.name && selection.index === index
      const hasError = Boolean(validation.nodes[nodeIndex]?.edges[index])
      const color = hasError ? EDGE_ERROR : active ? EDGE_ACTIVE : EDGE_COLOR
      const label = (edge.description || '').split('\n')[0].trim() || edge.function || 'Untitled transition'
      return {
        id: `${node.name}:${index}`,
        source: node.name,
        target: edge.target,
        type: 'transition',
        className: active ? 'is-active' : '',
        markerEnd: marker(color),
        style: { stroke: color, strokeWidth: active ? 2 : 1.5 },
        zIndex: active ? 10 : 0,
        data: { label, active, hasError, labelT: labelT(node.name, edge.target), select: { kind: 'edge', name: node.name, index }, onSelect: () => setSelection({ kind: 'edge', name: node.name, index }) },
      }
    }))
    if (virtual[START_ID]) {
      items.push({ id: `${START_ID}->`, source: START_ID, target: config.initial_node, type: 'transition', selectable: false,
        markerEnd: marker(EDGE_COLOR), style: { stroke: EDGE_COLOR, strokeWidth: 1.5 }, data: { select: AGENT } })
    }
    if (virtual[END_ID]) {
      config.nodes.filter((node) => node.end).forEach((node) => {
        const hangsUp = endsCall(node)
        items.push({ id: `${node.name}->${END_ID}`, source: node.name, target: END_ID, type: 'transition', selectable: false,
          markerEnd: marker(EDGE_COLOR),
          style: { stroke: EDGE_COLOR, strokeWidth: 1.5, strokeDasharray: hangsUp ? undefined : '5 5' },
          data: { select: { kind: 'node', name: node.name } } })
      })
    }
    return items
  }, [config, virtual, selection, validation])

  const onNodesChange = useCallback((changes) => {
    for (const change of changes) {
      if (change.type === 'dimensions' && change.dimensions) measuredRef.current[change.id] = change.dimensions
    }
    setPositions((current) => {
      let next = current
      for (const change of changes) {
        if (change.type === 'position' && change.position && change.id !== START_ID && change.id !== END_ID) {
          // A partial layout is replaced by what is on screen on the first move.
          if (next === current) next = { ...(layoutCompleteRef.current ? current : placedRef.current) }
          next[change.id] = change.position
        }
      }
      return next
    })
    // Keyboard selection (focus a node, then Enter) opens it in the inspector.
    const selected = changes.find((change) => change.type === 'select' && change.selected)
    if (selected && selected.id !== START_ID && selected.id !== END_ID) setSelection({ kind: 'node', name: selected.id })
  }, [])

  const onNodeDragStop = (_, moved) => {
    if (moved.id === START_ID || moved.id === END_ID) return
    // Pin every node where it is on screen, so auto-placed nodes do not jump later.
    const next = { ...placed, ...(layoutComplete ? positionsRef.current : {}), [moved.id]: moved.position }
    setPositions(next)
    persistLayout(agentId, next).catch((error) => showError(error, 'Node position not saved'))
  }

  const tidyUp = (sizes) => {
    const next = autoLayout(config, sizes)
    setPositions(next)
    persistLayout(agentId, next)
      .then(() => setMessage({ kind: 'success', text: 'Graph tidied. Node positions saved to the layout file.' }))
      .catch((error) => showError(error, 'Node positions not saved'))
  }

  const onNodeClick = (_, item) => {
    if (item.id === START_ID || item.id === END_ID) setSelection(AGENT)
    else setSelection({ kind: 'node', name: item.id })
  }
  const onEdgeClick = (_, item) => setSelection(item.data?.select || AGENT)

  // ---- Agent actions ------------------------------------------------------
  const takenIds = agents.map((agent) => agent.id)

  const createAgent = async () => {
    if (!(await confirmDiscard())) return
    const result = await ask({
      kind: 'name',
      title: 'New agent',
      body: 'Starts with a single node. You can add nodes and transitions on the canvas.',
      initialName: '',
      submitLabel: 'Create agent',
    })
    if (!result) return
    setBusy('create')
    try {
      await request('/api/agents', { method: 'POST', body: JSON.stringify({ id: result.id, name: result.name }) })
      await refreshAgents(result.id)
      setMessage({ kind: 'success', text: `Created ${result.name}` })
    } catch (error) {
      showError(error, 'Could not create the agent')
    } finally {
      setBusy('')
    }
  }

  const duplicateAgent = async () => {
    const result = await ask({
      kind: 'name',
      title: 'Duplicate agent',
      body: <>Copies the last saved version of <strong>{config.name}</strong>, with its layout.</>,
      note: dirty ? 'Your unsaved changes are not included and will be discarded.' : '',
      initialName: `${config.name} copy`,
      submitLabel: 'Duplicate',
    })
    if (!result) return
    setBusy('duplicate')
    try {
      const copy = await request(`/api/agents/${agentId}/duplicate`, { method: 'POST', body: JSON.stringify({ id: result.id }) })
      // The duplicate endpoint names the copy itself; apply the chosen name to the new agent only.
      if (copy.config.name !== result.name) {
        await request(`/api/agents/${result.id}`, { method: 'PUT', body: JSON.stringify({ ...copy.config, name: result.name }) })
      }
      await refreshAgents(result.id)
      setMessage({ kind: 'success', text: `Duplicated as ${result.name}` })
    } catch (error) {
      showError(error, 'Could not duplicate the agent')
    } finally {
      setBusy('')
    }
  }

  const deleteAgent = async () => {
    const name = config?.name || agentId
    const ok = await ask({
      kind: 'confirm',
      title: 'Delete this agent?',
      body: <>This removes <strong>{name}</strong> (<code>{agentId}</code>), its JSON file and its saved layout. It cannot be undone.</>,
      confirmLabel: 'Delete agent',
      danger: true,
    })
    if (!ok) return
    setBusy('delete')
    try {
      await request(`/api/agents/${agentId}`, { method: 'DELETE' })
      await refreshAgents()
      setMessage({ kind: 'success', text: `Deleted ${name}` })
    } catch (error) {
      showError(error, 'Could not delete the agent')
    } finally {
      setBusy('')
    }
  }

  // Shared by Save and Test call; returns true only when the agent was saved.
  const doSave = async () => {
    if (validation.count > 0) {
      setServerErrors([])
      setMessage({ kind: 'error', text: `Not saved: fix the ${validation.count} highlighted field${validation.count === 1 ? '' : 's'} first.` })
      return false
    }
    try {
      const payload = await request(`/api/agents/${agentId}`, { method: 'PUT', body: JSON.stringify(config) })
      setConfig(payload.config)
      setSavedSnapshot(JSON.stringify(payload.config))
      setServerErrors([])
      let layoutNote = ''
      await persistLayout(agentId, positionsRef.current).catch(() => { layoutNote = ' (node positions could not be saved)' })
      const list = await request('/api/agents')
      setAgents(list.agents)
      setMessage({ kind: 'success', text: `Saved at ${new Date().toLocaleTimeString()}${layoutNote}` })
      return true
    } catch (error) {
      showError(error, 'Save failed')
      return false
    }
  }

  const save = async () => {
    setBusy('save')
    setMessage({ kind: 'info', text: 'Saving…' })
    await doSave()
    setBusy('')
  }

  const testCall = async () => {
    setBusy('call')
    setMessage({ kind: 'info', text: 'Saving and opening the call…' })
    try {
      if (!(await doSave())) {
        setMessage((current) => ({ kind: 'error', text: `Test call not started. ${current.text}` }))
        return
      }
      const payload = await request(`/api/agents/${agentId}/test-call`, { method: 'POST' })
      const list = await request('/api/agents')
      setAgents(list.agents)
      const opened = window.open(payload.url, '_blank', 'noopener,noreferrer')
      setMessage({
        kind: 'success',
        text: opened === null
          ? `Saved and selected for the next call. The browser blocked the new tab: open ${payload.url} and click Connect.`
          : 'Saved and selected for the next call. The call client opened in a new tab: click Connect there.',
      })
    } catch (error) {
      showError(error, 'Test call failed')
    } finally {
      setBusy('')
    }
  }

  // ---- Node and edge actions ---------------------------------------------
  const addNode = () => {
    let index = config.nodes.length + 1
    while (config.nodes.some((node) => node.name === `node_${index}`)) index += 1
    const name = `node_${index}`
    patchConfig({ nodes: [...config.nodes, {
      name,
      role_message: null,
      task_messages: [{ role: 'developer', content: 'Describe this node objective.' }],
      edges: [], functions: [], pre_actions: [], post_actions: [], end: false, auto_end: true,
    }] })
    setSelection({ kind: 'node', name })
  }

  const deleteNode = async (name) => {
    if (config.nodes.length === 1) {
      setMessage({ kind: 'error', text: 'An agent must have at least one node.' })
      return
    }
    const incoming = config.nodes.reduce((count, item) =>
      count + item.edges.filter((edge) => edge.target === name).length, 0)
    const ok = await ask({
      kind: 'confirm',
      title: 'Delete this node?',
      body: <>Deletes <strong>{name}</strong> and its outgoing transitions.{incoming ? <> {incoming} transition{incoming === 1 ? '' : 's'} pointing to it will also be removed.</> : null}</>,
      confirmLabel: 'Delete node',
      danger: true,
    })
    if (!ok) return
    const remaining = config.nodes.filter((node) => node.name !== name)
    const initial = config.initial_node === name ? remaining[0].name : config.initial_node
    setConfig({
      ...config,
      initial_node: initial,
      nodes: remaining.map((node) => ({ ...node, edges: node.edges.filter((edge) => edge.target !== name) })),
    })
    setPositions((current) => {
      const next = { ...current }
      delete next[name]
      return next
    })
    setSelection(AGENT)
  }

  const addEdge = (source, target) => {
    const sourceNode = config.nodes.find((node) => node.name === source)
    patchNode(source, { edges: [...sourceNode.edges, blankEdge(target, sourceNode.edges.length)] })
    setSelection({ kind: 'edge', name: source, index: sourceNode.edges.length })
  }

  const deleteEdge = async (source, index) => {
    const edge = config.nodes.find((node) => node.name === source).edges[index]
    const ok = await ask({
      kind: 'confirm',
      title: 'Delete this transition?',
      body: <>Removes <code>{edge.function || '(unnamed)'}</code> from <strong>{source}</strong> to <strong>{edge.target}</strong>.</>,
      confirmLabel: 'Delete transition',
      danger: true,
    })
    if (!ok) return
    const sourceNode = config.nodes.find((node) => node.name === source)
    patchNode(source, { edges: sourceNode.edges.filter((_, i) => i !== index) })
    setSelection({ kind: 'node', name: source })
  }

  const onConnect = ({ source, target }) => {
    if (!source || !target || source === START_ID || target === END_ID || target === START_ID || source === END_ID) return
    addEdge(source, target)
  }

  // ---- Inspector ------------------------------------------------------------
  const nodeIndex = config && selection.kind !== 'agent' ? config.nodes.findIndex((item) => item.name === selection.name) : -1
  const node = nodeIndex >= 0 ? config.nodes[nodeIndex] : null
  const edge = node && selection.kind === 'edge' ? node.edges[selection.index] : null
  const nodeErrors = validation.nodes[nodeIndex] || { edges: {} }

  let inspector = null
  if (config && edge) {
    inspector = <EdgeInspector
      key={`${node.name}:${selection.index}`}
      source={node} edge={edge} index={selection.index} nodes={config.nodes}
      errors={nodeErrors.edges[selection.index] || {}}
      onPatch={(patch) => patchNode(node.name, { edges: node.edges.map((item, i) => i === selection.index ? { ...item, ...patch } : item) })}
      onDelete={() => deleteEdge(node.name, selection.index)}
      onOpenNode={() => setSelection({ kind: 'node', name: node.name })}
    />
  } else if (config && node && selection.kind === 'node') {
    inspector = <NodeInspector
      key={node.name}
      node={node} nodes={config.nodes} tools={tools} errors={nodeErrors}
      isInitial={config.initial_node === node.name}
      onPatch={(patch) => patchNode(node.name, patch)}
      onRename={(name) => renameNode(node.name, name)}
      onDelete={() => deleteNode(node.name)}
      onOpenEdge={(index) => setSelection({ kind: 'edge', name: node.name, index })}
      onAddEdge={() => addEdge(node.name, config.nodes[0].name)}
    />
  } else if (config) {
    inspector = <AgentInspector config={config} errors={validation.agent} onPatch={patchConfig} />
  }

  const activeAgent = agents.find((agent) => agent.id === agentId)

  return <div className="app-shell">
    <header className="topbar">
      <div className="topbar__title">
        <span className="brand">Agent editor</span>
        {config && <>
          <span className="crumb-sep">/</span>
          <span className="crumb">{config.name || agentId}</span>
          <span className={`unsaved ${dirty ? '' : 'is-hidden'}`} aria-hidden={!dirty}>Unsaved changes</span>
        </>}
      </div>
      <div className="toolbar">
        <button type="button" className="btn btn-ghost" onClick={addNode} disabled={!config || locked}><PlusIcon size={15} />Add node</button>
        <ActionButton onClick={save} disabled={!config || locked} loading={busy === 'save'}>Save</ActionButton>
        <ActionButton className="btn-primary" onClick={testCall} disabled={!config || locked} loading={busy === 'call'}><PhoneIcon size={15} />Test call</ActionButton>
      </div>
    </header>
    <div className={`status-bar ${message.kind}`} role="status" aria-live="polite">
      <span className="status-dot" aria-hidden="true" />
      <span>{message.text}</span>
      {serverErrors.length > 1 && <ul>{serverErrors.slice(1).map((error, index) => <li key={index}>{error}</li>)}</ul>}
    </div>
    <main>
      <aside className="agents-panel" aria-label="Agents">
        <div className="panel-head"><h2>Agents</h2><span className="count">{agents.length}</span></div>
        <div className="agent-actions">
          <ActionButton className="btn-sm" onClick={createAgent} disabled={locked} loading={busy === 'create'}>New</ActionButton>
          <ActionButton className="btn-sm" onClick={duplicateAgent} disabled={!agentId || locked} loading={busy === 'duplicate'}>Duplicate</ActionButton>
          <ActionButton className="btn-sm btn-danger-ghost" onClick={deleteAgent} disabled={!agentId || locked} loading={busy === 'delete'}>Delete</ActionButton>
        </div>
        <nav className="agent-list">
          {agents.map((agent) => <button
            type="button"
            key={agent.id}
            className={`agent-item${agent.id === agentId ? ' is-current' : ''}`}
            aria-current={agent.id === agentId ? 'true' : undefined}
            disabled={locked}
            onClick={() => loadAgent(agent.id)}
          >
            <span className="agent-item__name">{agent.name}{agent.id === agentId && dirty ? <span className="dirty-dot" title="Unsaved changes" /> : null}</span>
            <span className="agent-item__meta">
              <span>{agent.nodes} node{agent.nodes === 1 ? '' : 's'}</span>
              {agent.active && <span className="next-call">Next call</span>}
            </span>
          </button>)}
        </nav>
        {activeAgent && <p className="panel-note">Test call saves the agent and makes it the one the next call uses.</p>}
      </aside>
      <section className="canvas-panel" aria-label="Agent graph">
        {config && <ReactFlowProvider key={agentId}>
          <ReactFlow
            nodes={graphNodes}
            edges={graphEdges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={onNodesChange}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            onPaneClick={() => setSelection(AGENT)}
            onNodeDragStop={onNodeDragStop}
            onConnect={onConnect}
            deleteKeyCode={null}
            zoomOnDoubleClick={false}
            // Focusing a node on click must not pan the canvas: it would move the
            // node away from the pointer and break double-click to rename.
            autoPanOnNodeFocus={false}
            fitView
            fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
            minZoom={0.2}
            maxZoom={2}
          >
            <Background gap={20} size={1.4} color="#d4d4d1" />
            <CanvasControls onTidy={tidyUp} disabled={locked} />
          </ReactFlow>
        </ReactFlowProvider>}
      </section>
      <aside className="inspector-panel" aria-label="Inspector">{inspector}</aside>
    </main>
    {dialog?.kind === 'confirm' && <ConfirmDialog {...dialog} onResult={closeDialog} />}
    {dialog?.kind === 'name' && <NameDialog {...dialog} takenIds={takenIds} onResult={closeDialog} />}
  </div>
}
