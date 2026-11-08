import { useEffect, useMemo, useState } from 'react'
import { Background, Controls, MiniMap, ReactFlow } from '@xyflow/react'

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

export default function App() {
  const [agents, setAgents] = useState([])
  const [agentId, setAgentId] = useState('')
  const [config, setConfig] = useState(null)
  const [selectedNode, setSelectedNode] = useState('')
  const [positions, setPositions] = useState({})
  const [tools, setTools] = useState([])
  const [status, setStatus] = useState('Loading agents…')
  const [errors, setErrors] = useState([])

  const refreshAgents = async (preferred) => {
    const payload = await request('/api/agents')
    setAgents(payload.agents)
    const next = preferred || payload.active_agent_id || payload.agents[0]?.id
    if (next) await loadAgent(next)
  }

  const loadAgent = async (id) => {
    try {
      const payload = await request(`/api/agents/${id}`)
      setAgentId(id)
      setConfig(payload.config)
      setSelectedNode(payload.config.initial_node)
      setPositions({})
      setErrors([])
      setStatus(`Loaded ${payload.config.name}`)
    } catch (error) {
      setErrors(error.errors || [error.message])
    }
  }

  useEffect(() => {
    Promise.all([request('/api/agents'), request('/api/tools')])
      .then(([agentPayload, toolPayload]) => {
        setAgents(agentPayload.agents)
        setTools(toolPayload.tools)
        const id = agentPayload.active_agent_id || agentPayload.agents[0]?.id
        if (id) loadAgent(id)
        else setStatus('Create an agent to begin.')
      })
      .catch((error) => setErrors(error.errors || [error.message]))
  }, [])

  const graphNodes = useMemo(() => (config?.nodes || []).map((node, index) => ({
    id: node.name,
    position: positions[node.name] || { x: 80 + (index % 3) * 260, y: 80 + Math.floor(index / 3) * 180 },
    data: { label: node.name },
    className: `${node.end ? 'terminal-node' : ''} ${node.name === selectedNode ? 'selected-node' : ''}`,
  })), [config, positions, selectedNode])

  const graphEdges = useMemo(() => (config?.nodes || []).flatMap((node) =>
    (node.edges || []).map((edge, index) => ({
      id: `${node.name}:${edge.function}:${index}`,
      source: node.name,
      target: edge.target,
      label: edge.function,
      markerEnd: { type: 'arrowclosed' },
    }))), [config])

  const patchConfig = (patch) => setConfig((current) => ({ ...current, ...patch }))
  const patchNode = (name, patch) => setConfig((current) => ({
    ...current,
    nodes: current.nodes.map((node) => node.name === name ? { ...node, ...patch } : node),
  }))

  const renameNode = (oldName, newName) => {
    const clean = newName.trim()
    if (!clean || (clean !== oldName && config.nodes.some((node) => node.name === clean))) {
      setErrors(['Node names must be non-empty and unique.'])
      return
    }
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
      const next = { ...current, [clean]: current[oldName] }
      delete next[oldName]
      return next
    })
    setSelectedNode(clean)
    setErrors([])
  }

  const createAgent = async () => {
    const id = window.prompt('Agent id (lowercase letters, numbers, - or _):')
    if (!id) return
    try {
      await request('/api/agents', { method: 'POST', body: JSON.stringify({ id }) })
      await refreshAgents(id)
      setStatus(`Created ${id}`)
    } catch (error) { setErrors(error.errors || [error.message]) }
  }

  const duplicateAgent = async () => {
    const id = window.prompt('Id for the duplicate:')
    if (!id) return
    try {
      await request(`/api/agents/${agentId}/duplicate`, {
        method: 'POST', body: JSON.stringify({ id }),
      })
      await refreshAgents(id)
      setStatus(`Duplicated as ${id}`)
    } catch (error) { setErrors(error.errors || [error.message]) }
  }

  const deleteAgent = async () => {
    if (!window.confirm(`Delete ${agentId}? This removes its JSON file.`)) return
    try {
      await request(`/api/agents/${agentId}`, { method: 'DELETE' })
      setConfig(null)
      setAgentId('')
      await refreshAgents()
      setStatus('Agent deleted')
    } catch (error) { setErrors(error.errors || [error.message]) }
  }

  const save = async () => {
    try {
      const payload = await request(`/api/agents/${agentId}`, {
        method: 'PUT', body: JSON.stringify(config),
      })
      setConfig(payload.config)
      setErrors([])
      setStatus(`Saved ${new Date().toLocaleTimeString()}`)
      const list = await request('/api/agents')
      setAgents(list.agents)
      return true
    } catch (error) {
      setErrors(error.errors || [error.message])
      setStatus('Validation failed')
      return false
    }
  }

  const testCall = async () => {
    if (!(await save())) return
    try {
      const payload = await request(`/api/agents/${agentId}/test-call`, { method: 'POST' })
      const list = await request('/api/agents')
      setAgents(list.agents)
      setStatus(`Selected ${agentId} for the next call`)
      window.open(payload.url, '_blank', 'noopener,noreferrer')
    } catch (error) { setErrors(error.errors || [error.message]) }
  }

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
    setSelectedNode(name)
  }

  const deleteNode = () => {
    if (config.nodes.length === 1) return setErrors(['An agent must have at least one node.'])
    const remaining = config.nodes.filter((node) => node.name !== selectedNode)
    const initial = config.initial_node === selectedNode ? remaining[0].name : config.initial_node
    setConfig({
      ...config,
      initial_node: initial,
      nodes: remaining.map((node) => ({
        ...node,
        edges: node.edges.filter((edge) => edge.target !== selectedNode),
      })),
    })
    setSelectedNode(initial)
  }

  const addGraphEdge = ({ source, target }) => {
    if (!source || !target) return
    const sourceNode = config.nodes.find((node) => node.name === source)
    patchNode(source, { edges: [...sourceNode.edges, blankEdge(target, sourceNode.edges.length)] })
    setSelectedNode(source)
  }

  const node = config?.nodes.find((item) => item.name === selectedNode)

  return <div className="app-shell">
    <header>
      <div><strong>Prosper Agent Editor</strong><span>{status}</span></div>
      <div className="toolbar">
        <button onClick={addNode} disabled={!config}>Add node</button>
        <button className="primary" onClick={save} disabled={!config}>Save</button>
        <button className="call" onClick={testCall} disabled={!config}>Test call</button>
      </div>
    </header>
    {errors.length > 0 && <div className="error-panel">
      {errors.map((error, index) => <div key={index}>{error}</div>)}
    </div>}
    <main>
      <aside className="agents-panel">
        <div className="panel-title">Agents</div>
        <div className="agent-actions">
          <button onClick={createAgent}>New</button>
          <button onClick={duplicateAgent} disabled={!agentId}>Duplicate</button>
          <button onClick={deleteAgent} disabled={!agentId}>Delete</button>
        </div>
        <div className="agent-list">
          {agents.map((agent) => <button
            key={agent.id}
            className={agent.id === agentId ? 'active-agent' : ''}
            onClick={() => loadAgent(agent.id)}
          >
            <strong>{agent.name}</strong>
            <small>{agent.nodes} nodes{agent.active ? ' · next call' : ''}</small>
          </button>)}
        </div>
        {config && <div className="agent-settings">
          <label>Agent name<input value={config.name} onChange={(event) => patchConfig({ name: event.target.value })} /></label>
          <label>Persona<textarea rows="7" value={config.persona || ''} onChange={(event) => patchConfig({ persona: event.target.value })} /></label>
          <label>Initial node<select value={config.initial_node} onChange={(event) => patchConfig({ initial_node: event.target.value })}>
            {config.nodes.map((item) => <option key={item.name}>{item.name}</option>)}
          </select></label>
        </div>}
      </aside>
      <section className="canvas-panel">
        {config && <ReactFlow
          nodes={graphNodes}
          edges={graphEdges}
          onNodeClick={(_, selected) => setSelectedNode(selected.id)}
          onNodeDragStop={(_, moved) => setPositions((current) => ({ ...current, [moved.id]: moved.position }))}
          onConnect={addGraphEdge}
          fitView
        >
          <MiniMap pannable zoomable />
          <Controls />
          <Background gap={18} size={1} />
        </ReactFlow>}
      </section>
      <aside className="inspector-panel">
        <div className="panel-title">Node inspector</div>
        {node ? <NodeEditor
          key={node.name}
          node={node}
          nodes={config.nodes}
          tools={tools}
          onPatch={(patch) => patchNode(node.name, patch)}
          onRename={(name) => renameNode(node.name, name)}
          onDelete={deleteNode}
        /> : <p>Select a node.</p>}
      </aside>
    </main>
  </div>
}

function NodeEditor({ node, nodes, tools, onPatch, onRename, onDelete }) {
  const [name, setName] = useState(node.name)
  const updateMessage = (index, patch) => onPatch({
    task_messages: node.task_messages.map((message, i) => i === index ? { ...message, ...patch } : message),
  })
  const updateEdge = (index, patch) => onPatch({
    edges: node.edges.map((edge, i) => i === index ? { ...edge, ...patch } : edge),
  })

  return <div className="node-editor">
    <label>Node name<input value={name} onChange={(event) => setName(event.target.value)} onBlur={() => onRename(name)} /></label>
    <label>Role message<textarea rows="4" value={node.role_message || ''} onChange={(event) => onPatch({ role_message: event.target.value || null })} /></label>
    <label className="checkbox"><input type="checkbox" checked={node.end} onChange={(event) => onPatch({ end: event.target.checked })} /> Terminal node</label>
    <div className="subhead">Attached tools</div>
    <div className="tool-grid">{tools.map((tool) => <label className="checkbox" key={tool}>
      <input type="checkbox" checked={node.functions.includes(tool)} onChange={(event) => onPatch({
        functions: event.target.checked ? [...node.functions, tool] : node.functions.filter((item) => item !== tool),
      })} /> {tool}
    </label>)}</div>
    <div className="subhead row"><span>Task messages</span><button onClick={() => onPatch({ task_messages: [...node.task_messages, { role: 'developer', content: '' }] })}>Add</button></div>
    {node.task_messages.map((message, index) => <div className="card" key={index}>
      <div className="row"><select value={message.role} onChange={(event) => updateMessage(index, { role: event.target.value })}>
        <option value="developer">developer</option><option value="system">system</option><option value="user">user</option>
      </select><button onClick={() => onPatch({ task_messages: node.task_messages.filter((_, i) => i !== index) })}>Remove</button></div>
      <textarea rows="5" value={message.content} onChange={(event) => updateMessage(index, { content: event.target.value })} />
    </div>)}
    <div className="subhead row"><span>Edges</span><button onClick={() => onPatch({ edges: [...node.edges, blankEdge(nodes[0].name, node.edges.length)] })}>Add</button></div>
    {node.edges.map((edge, index) => <div className="card" key={index}>
      <label>Function<input value={edge.function} onChange={(event) => updateEdge(index, { function: event.target.value })} /></label>
      <label>Description<textarea rows="3" value={edge.description} onChange={(event) => updateEdge(index, { description: event.target.value })} /></label>
      <label>Target<select value={edge.target} onChange={(event) => updateEdge(index, { target: event.target.value })}>
        {nodes.map((item) => <option key={item.name}>{item.name}</option>)}
      </select></label>
      <button onClick={() => onPatch({ edges: node.edges.filter((_, i) => i !== index) })}>Delete edge</button>
    </div>)}
    <button className="danger" onClick={onDelete}>Delete node</button>
  </div>
}
