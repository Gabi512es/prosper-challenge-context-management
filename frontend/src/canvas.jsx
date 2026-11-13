import { useEffect, useRef, useState } from 'react'
import {
  BaseEdge, EdgeLabelRenderer, Handle, Panel, Position, getBezierPath, useReactFlow, useViewport,
} from '@xyflow/react'
import { BranchIcon, FitIcon, FlagIcon, MinusIcon, NodeIcon, PhoneOffIcon, PlusIcon, TidyIcon, WrenchIcon } from './icons.jsx'

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

function AgentNode({ data }) {
  const { node, active, hasError, onRename, onOpenTools } = data
  const preview = node.task_messages?.find((message) => message.content?.trim())?.content.trim()
  const tools = node.functions?.length || 0
  return <div className={`flow-node${active ? ' is-active' : ''}${hasError ? ' has-error' : ''}`}>
    <Handle type="target" position={Position.Top} />
    <div className="flow-node__body">
      <div className="flow-node__head">
        <NodeIcon size={18} />
        <NodeTitle name={node.name} onRename={onRename} />
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
    <Handle type="source" position={Position.Bottom} />
  </div>
}

function StartNode() {
  return <div className="flow-pill" title="Calls start here. Change the first step in the agent settings.">
    <FlagIcon size={18} /><span>Start</span>
    <Handle type="source" position={Position.Bottom} isConnectable={false} />
  </div>
}

function EndNode() {
  return <div className="flow-pill" title="Steps that end the call lead here.">
    <Handle type="target" position={Position.Top} isConnectable={false} />
    <PhoneOffIcon size={18} /><span>End</span>
  </div>
}

export const nodeTypes = { agent: AgentNode, start: StartNode, end: EndNode }

// Point at t on the same cubic curve getBezierPath draws for a bottom-to-top edge.
// Labels move toward the end where sibling edges fan out, so they do not stack.
function labelPoint(sx, sy, tx, ty, t) {
  const distance = ty - sy
  const offset = distance >= 0 ? 0.5 * distance : 0.25 * 25 * Math.sqrt(-distance)
  const [c1y, c2y] = [sy + offset, ty - offset]
  const u = 1 - t
  const x = u ** 3 * sx + 3 * u * u * t * sx + 3 * u * t * t * tx + t ** 3 * tx
  const y = u ** 3 * sy + 3 * u * u * t * c1y + 3 * u * t * t * c2y + t ** 3 * ty
  return [x, y]
}

function TransitionEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style, data }) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  const [labelX, labelY] = labelPoint(sourceX, sourceY, targetX, targetY, data?.labelT ?? 0.5)
  return <>
    <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} interactionWidth={22} />
    {data?.label && <EdgeLabelRenderer>
      <button
        type="button"
        className={`edge-pill nodrag nopan${data.active ? ' is-active' : ''}${data.hasError ? ' has-error' : ''}`}
        style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
        title={data.label}
        onClick={(event) => { event.stopPropagation(); data.onSelect() }}
      >
        <BranchIcon size={14} />
        <span>{data.label}</span>
      </button>
    </EdgeLabelRenderer>}
  </>
}

export const edgeTypes = { transition: TransitionEdge }

// Bottom control bar, styled after the reference: zoom, fit and Tidy up.
export function CanvasControls({ onTidy, disabled }) {
  const { zoomIn, zoomOut, zoomTo, fitView, getNodes } = useReactFlow()
  const { zoom } = useViewport()
  const tidy = () => {
    const sizes = Object.fromEntries(getNodes().map((item) => [item.id, item.measured]))
    onTidy(sizes)
    // Wait for the new positions to render before framing them.
    requestAnimationFrame(() => requestAnimationFrame(() => fitView({ padding: 0.2, duration: 300 })))
  }
  return <Panel position="bottom-center" className="canvas-controls" aria-label="Canvas controls">
    <button type="button" onClick={() => zoomOut({ duration: 150 })} aria-label="Zoom out"><MinusIcon size={18} /></button>
    <button type="button" className="zoom-value" onClick={() => zoomTo(1, { duration: 150 })} title="Reset to 100%">{Math.round(zoom * 100)}%</button>
    <button type="button" onClick={() => zoomIn({ duration: 150 })} aria-label="Zoom in"><PlusIcon size={18} /></button>
    <span className="divider" />
    <button type="button" onClick={() => fitView({ padding: 0.2, duration: 300 })} aria-label="Fit to screen" title="Fit to screen"><FitIcon size={18} /></button>
    <span className="divider" />
    <button type="button" className="with-label" onClick={tidy} disabled={disabled} title="Lay out the graph top to bottom">
      <TidyIcon size={18} /><span>Tidy up</span>
    </button>
  </Panel>
}
