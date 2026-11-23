import dagre from '@dagrejs/dagre'

// Start and End exist only on the canvas. They are derived from initial_node and
// terminal nodes on every render and are never written to the agent JSON or the
// layout file.
export const START_ID = '__start__'
export const END_ID = '__end__'
export const LANE_ID = '__any_time__'
export const LANE_GAP = 140
export const NODE_W = 288
export const START_W = 116
export const END_W = 104
export const PILL_H = 46
export const RANK_SEP = 120

export const estimateHeight = (node) => 118 + (node.functions?.length ? 36 : 0)

// A terminal node ends the call on its own when it has the builder's
// end_conversation post action, explicit or implied by auto_end.
export const endsCall = (node) => node.post_actions?.length
  ? node.post_actions.some((action) => action?.type === 'end_conversation')
  : Boolean(node.end && node.auto_end !== false)

const hasInitial = (config) => config.nodes.some((node) => node.name === config.initial_node)

// Top-to-bottom layout of every node. Start and End take part so the real
// nodes leave room for them. Returns top-left positions keyed by node name.
export function autoLayout(config, sizes = {}) {
  const graph = new dagre.graphlib.Graph({ multigraph: true })
  graph.setGraph({ rankdir: 'TB', nodesep: 120, ranksep: RANK_SEP, marginx: 0, marginy: 0 })
  graph.setDefaultEdgeLabel(() => ({}))
  const size = (id, width, height) => ({ width: sizes[id]?.width || width, height: sizes[id]?.height || height })
  config.nodes.forEach((node) => graph.setNode(node.name, size(node.name, NODE_W, estimateHeight(node))))
  if (hasInitial(config)) {
    graph.setNode(START_ID, size(START_ID, START_W, PILL_H))
    graph.setEdge(START_ID, config.initial_node, {}, 'start')
  }
  const terminals = config.nodes.filter((node) => node.end)
  if (terminals.length) graph.setNode(END_ID, size(END_ID, END_W, PILL_H))
  config.nodes.forEach((node) => {
    node.edges.forEach((edge, index) => {
      if (graph.hasNode(edge.target) && edge.target !== node.name) graph.setEdge(node.name, edge.target, {}, `${node.name}:${index}`)
    })
    if (node.end) graph.setEdge(node.name, END_ID, {}, `${node.name}:end`)
  })
  dagre.layout(graph)
  const positions = {}
  config.nodes.forEach((node) => {
    const { x, y, width, height } = graph.node(node.name)
    positions[node.name] = { x: Math.round(x - width / 2), y: Math.round(y - height / 2) }
  })
  return positions
}

// Start sits one rank above the initial node, End one rank below the lowest
// terminal node, centred on the terminals (or under `endUnder`, when given).
export function virtualPositions(config, positions, heightOf, { endUnder } = {}) {
  const result = {}
  const initial = positions[config.initial_node]
  if (initial && hasInitial(config)) {
    result[START_ID] = { x: initial.x + NODE_W / 2 - START_W / 2, y: initial.y - PILL_H - RANK_SEP }
  }
  const terminals = config.nodes.filter((node) => node.end && positions[node.name])
  if (terminals.length) {
    const centre = endUnder && positions[endUnder] ? positions[endUnder].x + NODE_W / 2
      : terminals.reduce((sum, node) => sum + positions[node.name].x + NODE_W / 2, 0) / terminals.length
    const bottom = Math.max(...terminals.map((node) => positions[node.name].y + heightOf(node)))
    result[END_ID] = { x: centre - END_W / 2, y: bottom + RANK_SEP }
  }
  return result
}

const ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/

export function slugify(name) {
  return name.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 64).replace(/_+$/, '')
}

export function uniqueId(base, taken) {
  if (!base || !taken.includes(base)) return base
  let index = 2
  while (taken.includes(`${base}_${index}`)) index += 1
  return `${base}_${index}`
}

export function idError(id, taken) {
  if (!id) return 'An id is required.'
  if (!ID_PATTERN.test(id)) return 'Use lowercase letters, numbers, - or _, starting with a letter or number.'
  if (taken.includes(id)) return 'Another agent already uses this id.'
  return ''
}

// ---- Fixed (v4) graphs --------------------------------------------------------
// Steps no transition leads to can happen at any time (a request for a person,
// an emergency). They sit in their own column on the right, labelled "Any time".
export function anyTimeSteps(config) {
  const targets = new Set(config.nodes.flatMap((node) => node.edges.map((edge) => edge.target)))
  return config.nodes.filter((node) => node.name !== config.initial_node && !targets.has(node.name)).map((node) => node.name)
}

// The last terminal step of the main path: End sits under it.
export function mainPathEnd(config) {
  const anyTime = new Set(anyTimeSteps(config))
  const terminals = config.nodes.filter((node) => node.end && !anyTime.has(node.name))
  return terminals.length ? terminals[terminals.length - 1].name : undefined
}

// The main path laid out by dagre top to bottom with measured sizes, so nodes
// never overlap; the any-time steps stacked in a column to its right.
export function fixedLayout(config, sizes = {}) {
  const anyTime = new Set(anyTimeSteps(config))
  const main = { ...config, nodes: config.nodes.filter((node) => !anyTime.has(node.name))
    // Forward edges only: back edges (cancel, change) still draw but do not bend the column.
    .map((node, index, nodes) => ({ ...node, end: false, edges: node.edges.filter((edge) =>
      !anyTime.has(edge.target) && nodes.findIndex((other) => other.name === edge.target) > index) })) }
  const positions = autoLayout(main, sizes)
  const width = (name) => sizes[name]?.width || NODE_W
  const height = (name) => sizes[name]?.height || estimateHeight(config.nodes.find((node) => node.name === name))
  const right = Math.max(...main.nodes.map((node) => positions[node.name].x + width(node.name)))
  let y = Math.min(...main.nodes.map((node) => positions[node.name].y))
  config.nodes.filter((node) => anyTime.has(node.name)).forEach((node) => {
    positions[node.name] = { x: right + LANE_GAP, y }
    y += height(node.name) + RANK_SEP / 2
  })
  return positions
}

// The dashed "Any time" box around the column, its label inside the top edge.
export const LANE_PAD = 20
export const LANE_HEAD = 34
export function laneBox(config, positions, sizeOf) {
  const names = anyTimeSteps(config).filter((name) => positions[name])
  if (!names.length) return null
  const boxes = names.map((name) => ({ ...positions[name], ...sizeOf(name) }))
  const x = Math.min(...boxes.map((box) => box.x)) - LANE_PAD
  const y = Math.min(...boxes.map((box) => box.y)) - LANE_PAD - LANE_HEAD
  const right = Math.max(...boxes.map((box) => box.x + box.w)) + LANE_PAD
  const bottom = Math.max(...boxes.map((box) => box.y + box.h)) + LANE_PAD
  return { x, y, w: right - x, h: bottom - y }
}

// ---- Orthogonal edge routing ---------------------------------------------------
// Forward edges run from the bottom of a step down into the top of the next.
// Backward edges (to a step higher up) leave from the left side and run up a lane
// left of the column into the target's left side. Backward edges to the same step
// share one lane and one entry, so they merge into a single arrowhead (flowchart
// style); each target has its own lane, the closest targets on the inner lanes.
// On a step's left side the exits sit above the entry, the inner lane's exit
// above the outer's, so that no two lanes cross.
export const BACK_LANE = 34
export const LANE_STEP = 24
const SIDE_STEP = 12

export function routeEdges(edges, boxOf, order) {
  const routes = {}
  const groups = {}
  edges.filter(({ source, target }) => boxOf(target).y + 1 < boxOf(source).y)
    .forEach((edge) => (groups[edge.target] ||= []).push(edge))
  const span = (target) => Math.max(...groups[target].map((edge) => Math.abs(order[edge.source] - order[target])))
  const targets = Object.keys(groups).sort((a, b) => span(a) - span(b) || order[a] - order[b])
  const sides = {}
  targets.forEach((target, lane) => {
    const offset = BACK_LANE + LANE_STEP * lane
    // One lane x for the whole group, left of every step it joins.
    const laneX = Math.min(boxOf(target).x, ...groups[target].map((edge) => boxOf(edge.source).x)) - offset
    groups[target].forEach((edge) => {
      routes[edge.id] = { kind: 'back', lane, offset, laneX, merged: groups[target].length > 1 }
      ;(sides[edge.source] ||= []).push({ ids: [edge.id], out: true, lane })
    })
    ;(sides[target] ||= []).push({ ids: groups[target].map((edge) => edge.id), out: false, lane })
  })
  Object.entries(sides).forEach(([name, list]) => {
    const outs = list.filter((item) => item.out).sort((a, b) => a.lane - b.lane)
    const ins = list.filter((item) => !item.out).sort((a, b) => b.lane - a.lane)
    const all = [...outs, ...ins]
    const limit = Math.max(0, boxOf(name).h / 2 - 10)
    all.forEach((item, index) => {
      const dy = Math.max(-limit, Math.min(limit, (index - (all.length - 1) / 2) * SIDE_STEP))
      item.ids.forEach((id) => { routes[id][item.out ? 'exitDy' : 'entryDy'] = dy })
    })
  })
  edges.forEach((edge) => { routes[edge.id] ||= { kind: 'forward' } })
  return routes
}

// The any-time steps' edges to End: out of the right side, down a lane right of
// the column, into End's right side. The top step takes the outer lane and the
// lower entry, so the two never cross.
export function sideRoutes(names) {
  return Object.fromEntries(names.map((name, index) => {
    const rank = names.length - 1 - index
    return [name, { kind: 'side', gap: LANE_PAD + 14 + LANE_STEP * rank, entryDy: (rank - (names.length - 1) / 2) * 10 }]
  }))
}
