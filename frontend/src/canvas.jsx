import { useEffect, useRef, useState } from 'react'
import { BaseEdge, Handle, Panel, Position, useReactFlow, useViewport } from '@xyflow/react'
import { FitIcon, FlagIcon, MinusIcon, NodeIcon, PhoneOffIcon, PlusIcon, WrenchIcon } from './icons.jsx'

function NodeTitle({ name, onRename }) {
  const [draft, setDraft] = useState(null)
  const [invalid, setInvalid] = useState(false)
  const inputRef = useRef(null)
  useEffect(() => { if (draft !== null) inputRef.current?.select() }, [draft !== null])

  const commit = () => {
    if (onRename(draft)) { setDraft(null); setInvalid(false) } else setInvalid(true)
  }
  if (draft === null) {
    return <span className="flow-node__title" title="Double-click to rename"
      onDoubleClick={(event) => { event.stopPropagation(); setDraft(name) }}>{name}</span>
  }
  return <input
    ref={inputRef}
    className="flow-node__rename nodrag nopan"
    aria-label="Node name"
    aria-invalid={invalid}
    title={invalid ? 'Names must be unique and not empty.' : 'Enter to rename, Escape to cancel'}
    value={draft}
    onChange={(event) => { setDraft(event.target.value); setInvalid(false) }}
    onClick={(event) => event.stopPropagation()}
    // Leaving the field applies a valid name and silently reverts an invalid one.
    onBlur={() => { onRename(draft); setDraft(null); setInvalid(false) }}
    onKeyDown={(event) => {
      if (event.key === 'Enter') { event.preventDefault(); commit() }
      if (event.key === 'Escape') { setDraft(null); setInvalid(false) }
    }}
  />
}

// Four handles per step. In loose connection mode each one can start or end an
// edge; the edge's route picks the side (forward: bottom to top, back: left).
function Handles({ connectable = true, sides = ['top', 'right', 'bottom', 'left'] }) {
  const positions = { top: Position.Top, right: Position.Right, bottom: Position.Bottom, left: Position.Left }
  return sides.map((side) => <Handle key={side} id={side} type="source" position={positions[side]} isConnectable={connectable} />)
}

function AgentNode({ data }) {
  const { node, title, summary, fixed, active, hasError, onRename, onOpenTools } = data
  const preview = summary || node.task_messages?.find((message) => message.content?.trim())?.content.trim() || node.description
  const tools = fixed ? 0 : node.functions?.length || 0
  return <div className={`flow-node${active ? ' is-active' : ''}${hasError ? ' has-error' : ''}${fixed ? ' is-fixed' : ''}`}>
    <Handles connectable={!fixed} />
    <div className="flow-node__body">
      <div className="flow-node__head">
        <NodeIcon size={18} />
        {fixed ? <span className="flow-node__title">{title}</span> : <NodeTitle name={node.name} onRename={onRename} />}
      </div>
      <p className={`flow-node__preview${preview ? '' : ' is-empty'}`}>{preview || 'No task message yet.'}</p>
    </div>
    {tools > 0 && <div className="flow-node__footer">
      <button
        type="button"
        className="tool-badge nodrag"
        title={`Actions: ${node.functions.join(', ')}`}
        aria-label={`${tools} action${tools === 1 ? '' : 's'}: ${node.functions.join(', ')}. Open in the inspector.`}
        onClick={(event) => { event.stopPropagation(); onOpenTools() }}
      >
        <WrenchIcon size={14} /><span>{tools}</span>
      </button>
    </div>}
  </div>
}

function StartNode() {
  return <div className="flow-pill" title="Calls start here.">
    <FlagIcon size={18} /><span>Start</span>
    <Handles connectable={false} sides={['bottom']} />
  </div>
}

function EndNode() {
  return <div className="flow-pill" title="Steps that end the call lead here.">
    <Handles connectable={false} sides={['top', 'right']} />
    <PhoneOffIcon size={18} /><span>End</span>
  </div>
}

// The dashed box around the steps that can happen at any time.
function LaneBox({ data }) {
  return <div className="lane-box" title={data.title} style={{ width: data.w, height: data.h }}>
    <span className="lane-box__label">{data.label}</span>
  </div>
}

export const nodeTypes = { agent: AgentNode, start: StartNode, end: EndNode, lane: LaneBox }

// Orthogonal edges only: straight segments and right angles, no curves.
export function orthogonalPath(route, sx, sy, tx, ty) {
  if (route?.kind === 'back') {
    const lane = route.laneX ?? Math.min(sx, tx) - route.offset
    const [y1, y2] = [sy + (route.exitDy || 0), ty + (route.entryDy || 0)]
    return `M ${sx},${y1} H ${lane} V ${y2} H ${tx}`
  }
  if (route?.kind === 'side') {
    const y2 = ty + (route.entryDy || 0)
    return `M ${sx},${sy} H ${sx + route.gap} V ${y2} H ${tx}`
  }
  // Ends a few pixels apart (a narrow Start or End pill under a card): one straight line.
  if (Math.abs(sx - tx) < 24) return `M ${tx},${sy} V ${ty}`
  const mid = sy + Math.max(16, (ty - sy) / 2)
  return `M ${sx},${sy} V ${mid} H ${tx} V ${ty}`
}

function TransitionEdge({ id, sourceX, sourceY, targetX, targetY, markerEnd, style, data }) {
  return <BaseEdge id={id} path={orthogonalPath(data?.route, sourceX, sourceY, targetX, targetY)}
    markerEnd={markerEnd} style={style} interactionWidth={18} />
}

export const edgeTypes = { transition: TransitionEdge }

// Bottom control bar: zoom and fit. Tidy up is in the top toolbar.
export function CanvasControls() {
  const { zoomIn, zoomOut, zoomTo, fitView } = useReactFlow()
  const { zoom } = useViewport()
  return <Panel position="bottom-center" className="canvas-controls" aria-label="Canvas controls">
    <button type="button" onClick={() => zoomOut({ duration: 150 })} aria-label="Zoom out"><MinusIcon size={18} /></button>
    <button type="button" className="zoom-value" onClick={() => zoomTo(1, { duration: 150 })} title="Reset to 100%">{Math.round(zoom * 100)}%</button>
    <button type="button" onClick={() => zoomIn({ duration: 150 })} aria-label="Zoom in"><PlusIcon size={18} /></button>
    <span className="divider" />
    <button type="button" onClick={() => fitView({ padding: 0.2, duration: 300 })} aria-label="Fit to screen" title="Fit to screen"><FitIcon size={18} /></button>
  </Panel>
}
