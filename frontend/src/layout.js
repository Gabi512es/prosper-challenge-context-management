import dagre from '@dagrejs/dagre'

// Start and End exist only on the canvas. They are derived from initial_node and
// terminal nodes on every render and are never written to the agent JSON or the
// layout file.
export const START_ID = '__start__'
export const END_ID = '__end__'
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
// terminal node, centred on the terminals.
export function virtualPositions(config, positions, heightOf) {
  const result = {}
  const initial = positions[config.initial_node]
  if (initial && hasInitial(config)) {
    result[START_ID] = { x: initial.x + NODE_W / 2 - START_W / 2, y: initial.y - PILL_H - RANK_SEP }
  }
  const terminals = config.nodes.filter((node) => node.end && positions[node.name])
  if (terminals.length) {
    const centre = terminals.reduce((sum, node) => sum + positions[node.name].x + NODE_W / 2, 0) / terminals.length
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
