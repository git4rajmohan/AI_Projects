import { useEffect, useRef, useState, useCallback } from 'react'
import * as d3 from 'd3'
import useAppStore from '../store/appStore'

const GROUP_COLORS = {
  root:      '#a78bfa',
  sources:   '#60a5fa',
  entities:  '#34d399',
  concepts:  '#fbbf24',
  analyses:  '#f87171',
}
const ALL_GROUPS = ['root', 'sources', 'entities', 'concepts', 'analyses']

function nodeColor(group) { return GROUP_COLORS[group] || '#94a3b8' }

const DEFAULT_FILTERS = {
  search: '',
  showOrphans: true,
  showAttachments: true,
  visibleGroups: Object.fromEntries(ALL_GROUPS.map(g => [g, true])),
}
const DEFAULT_DISPLAY = {
  nodeSize: 6,
  linkThickness: 1,
  labelMode: 'always', // 'always' | 'hover' | 'never'
  showArrows: false,
}
const DEFAULT_FORCES = {
  repel: -200,
  linkDistance: 80,
  gravity: 0.1,
}

/* ── tiny UI helpers ── */
function Section({ title, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-gray-700 last:border-0">
      <button
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-gray-300 hover:text-white"
        onClick={() => setOpen(o => !o)}
      >
        {title}
        <span className="text-gray-500 text-xs">{open ? '▾' : '▸'}</span>
      </button>
      {open && <div className="px-3 pb-3 flex flex-col gap-2">{children}</div>}
    </div>
  )
}

function Slider({ label, min, max, step, value, onChange }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex justify-between text-xs text-gray-400">
        <span>{label}</span><span>{value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full accent-purple-500 h-1 cursor-pointer" />
    </div>
  )
}

function Toggle({ label, checked, onChange }) {
  return (
    <label className="flex items-center justify-between text-xs text-gray-300 cursor-pointer select-none">
      <span>{label}</span>
      <div onClick={() => onChange(!checked)}
        className={`w-8 h-4 rounded-full transition-colors relative cursor-pointer shrink-0 ${checked ? 'bg-purple-600' : 'bg-gray-600'}`}>
        <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${checked ? 'translate-x-4' : 'translate-x-0.5'}`} />
      </div>
    </label>
  )
}

/* ── main component ── */
export default function GraphView({ onSelectPage }) {
  const svgRef    = useRef(null)
  const simRef    = useRef(null)
  const linkRef   = useRef(null)
  const nodeRef   = useRef(null)

  const { activeProject } = useAppStore()
  const [graphData,   setGraphData]   = useState(null)
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState(null)
  const [hoveredNode, setHoveredNode] = useState(null)
  const [panelOpen,   setPanelOpen]   = useState(false)

  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [display, setDisplay] = useState(DEFAULT_DISPLAY)
  const [forces,  setForces]  = useState(DEFAULT_FORCES)

  const setFilter  = (k, v) => setFilters(f => ({ ...f, [k]: v }))
  const setDisplay_ = (k, v) => setDisplay(d => ({ ...d, [k]: v }))
  const setForce   = (k, v) => setForces(f => ({ ...f, [k]: v }))

  /* fetch */
  useEffect(() => {
    if (!activeProject) return
    setLoading(true); setError(null)
    fetch(`/api/wiki/graph?project_id=${activeProject.id}`)
      .then(r => r.ok ? r.json() : Promise.reject('Failed to load graph'))
      .then(data => { setGraphData(data); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [activeProject])

  /* filtered data */
  const filteredData = useCallback(() => {
    if (!graphData) return { nodes: [], edges: [] }
    let { nodes, edges } = graphData

    nodes = nodes.filter(n => filters.visibleGroups[n.group] !== false)
    if (!filters.showAttachments) nodes = nodes.filter(n => n.group !== 'root')

    if (!filters.showOrphans) {
      const ids = new Set(nodes.map(n => n.id))
      const connected = new Set()
      edges.forEach(e => {
        const s = typeof e.source === 'object' ? e.source.id : e.source
        const t = typeof e.target === 'object' ? e.target.id : e.target
        if (ids.has(s) && ids.has(t)) { connected.add(s); connected.add(t) }
      })
      nodes = nodes.filter(n => connected.has(n.id))
    }

    const ids = new Set(nodes.map(n => n.id))
    edges = edges.filter(e => {
      const s = typeof e.source === 'object' ? e.source.id : e.source
      const t = typeof e.target === 'object' ? e.target.id : e.target
      return ids.has(s) && ids.has(t)
    })
    return { nodes, edges }
  }, [graphData, filters])

  /* build / rebuild D3 graph — runs on data+filter changes */
  useEffect(() => {
    if (!graphData || !svgRef.current) return
    const { nodes, edges } = filteredData()

    const container = svgRef.current.parentElement
    const W = container.clientWidth  || 800
    const H = container.clientHeight || 600

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    svg.attr('width', W).attr('height', H)
    if (nodes.length === 0) return

    const nodesCopy = nodes.map(n => ({ ...n }))
    const edgesCopy = edges.map(e => ({
      source: typeof e.source === 'object' ? e.source.id : e.source,
      target: typeof e.target === 'object' ? e.target.id : e.target,
    }))

    /* zoom */
    const g = svg.append('g')
    svg.call(d3.zoom().scaleExtent([0.1, 4]).on('zoom', ev => g.attr('transform', ev.transform)))

    /* arrow marker */
    svg.append('defs').append('marker')
      .attr('id', 'arrow').attr('viewBox', '0 -4 8 8')
      .attr('refX', 14).attr('refY', 0)
      .attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', '#475569')

    /* simulation */
    const sim = d3.forceSimulation(nodesCopy)
      .force('link',      d3.forceLink(edgesCopy).id(d => d.id).distance(forces.linkDistance).strength(0.5))
      .force('charge',    d3.forceManyBody().strength(forces.repel))
      .force('center',    d3.forceCenter(W / 2, H / 2).strength(forces.gravity))
      .force('collision', d3.forceCollide(forces.nodeSize + 10))
    simRef.current = sim

    /* edges */
    const link = g.append('g').attr('stroke', '#475569').attr('stroke-opacity', 0.5)
      .selectAll('line').data(edgesCopy).join('line')
      .attr('stroke-width', display.linkThickness)
      .attr('marker-end', display.showArrows ? 'url(#arrow)' : null)
    linkRef.current = link

    /* nodes */
    const node = g.append('g').selectAll('g').data(nodesCopy).join('g')
      .style('cursor', 'pointer')
      .call(d3.drag()
        .on('start', (ev, d) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
        .on('drag',  (ev, d) => { d.fx = ev.x; d.fy = ev.y })
        .on('end',   (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null })
      )
      .on('click',      (ev, d) => { ev.stopPropagation(); onSelectPage && onSelectPage(d.id) })
      .on('mouseenter', (_,  d) => setHoveredNode(d.id))
      .on('mouseleave', ()     => setHoveredNode(null))
    nodeRef.current = node

    node.append('circle')
      .attr('r',    d => d.group === 'root' ? display.nodeSize + 2 : display.nodeSize)
      .attr('fill', d => nodeColor(d.group))
      .attr('stroke', '#1e293b').attr('stroke-width', 1.5)

    node.append('text')
      .text(d => d.label)
      .attr('x', display.nodeSize + 4).attr('y', 4)
      .attr('font-size', '10px').attr('fill', '#cbd5e1')
      .attr('opacity', display.labelMode === 'never' ? 0 : 1)
      .style('pointer-events', 'none').style('user-select', 'none')

    sim.on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })

    /* search highlight */
    if (filters.search.trim()) {
      const q = filters.search.trim().toLowerCase()
      node.select('circle').attr('opacity', d => d.label.toLowerCase().includes(q) ? 1 : 0.12)
      node.select('text').attr('opacity',   d => d.label.toLowerCase().includes(q) ? 1 : 0.12)
      link.attr('stroke-opacity', 0.08)
    }

    return () => sim.stop()
  }, [graphData, filters]) // eslint-disable-line react-hooks/exhaustive-deps

  /* imperatively update forces — no rebuild */
  useEffect(() => {
    const sim = simRef.current
    if (!sim) return
    sim.force('link')?.distance(forces.linkDistance)
    sim.force('charge')?.strength(forces.repel)
    sim.force('center')?.strength(forces.gravity)
    sim.alpha(0.3).restart()
  }, [forces])

  /* imperatively update display props — no rebuild */
  useEffect(() => {
    const link = linkRef.current
    const node = nodeRef.current
    if (!link || !node) return
    link.attr('stroke-width', display.linkThickness)
        .attr('marker-end', display.showArrows ? 'url(#arrow)' : null)
    node.select('circle').attr('r', d => d.group === 'root' ? display.nodeSize + 2 : display.nodeSize)
    node.select('text').attr('x', display.nodeSize + 4)
                       .attr('opacity', display.labelMode === 'never' ? 0 : 1)
  }, [display])

  /* hover label mode */
  useEffect(() => {
    const node = nodeRef.current
    if (!node || display.labelMode !== 'hover') return
    node.select('text').attr('opacity', d => d.id === hoveredNode ? 1 : 0)
  }, [hoveredNode, display.labelMode])

  const groups = graphData ? [...new Set(graphData.nodes.map(n => n.group))] : []
  const { nodes: visNodes, edges: visEdges } = graphData ? filteredData() : { nodes: [], edges: [] }

  /* status screens */
  if (!activeProject) return <div className="flex items-center justify-center h-full text-gray-400 text-sm">Select a project to view the graph</div>
  if (loading)         return <div className="flex items-center justify-center h-full text-gray-400 text-sm">Loading graph…</div>
  if (error)           return <div className="flex items-center justify-center h-full text-red-400 text-sm">{error}</div>
  if (graphData && graphData.nodes.length === 0) return <div className="flex items-center justify-center h-full text-gray-400 text-sm">No wiki pages found. Ingest some sources first.</div>

  return (
    <div className="relative w-full h-full bg-gray-950 overflow-hidden">
      <svg ref={svgRef} className="w-full h-full" />

      {/* Legend */}
      {groups.length > 0 && (
        <div className="absolute bottom-3 left-3 flex flex-col gap-1 bg-gray-900/80 rounded px-3 py-2 text-xs text-gray-300 pointer-events-none">
          {groups.map(g => (
            <div key={g} className="flex items-center gap-2">
              <span className="inline-block w-3 h-3 rounded-full" style={{ background: nodeColor(g) }} />
              {g}
            </div>
          ))}
        </div>
      )}

      {/* Hover tooltip */}
      {hoveredNode && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 bg-gray-800 text-gray-100 text-xs px-3 py-1 rounded shadow pointer-events-none">
          {hoveredNode}
        </div>
      )}

      {/* Stats */}
      <div className="absolute top-3 left-3 text-xs text-gray-500 pointer-events-none">
        {visNodes.length} nodes · {visEdges.length} links
      </div>

      {/* Settings toggle */}
      <button
        onClick={() => setPanelOpen(o => !o)}
        title="Graph settings"
        className={`absolute top-3 right-3 w-7 h-7 flex items-center justify-center rounded text-sm z-10 transition-colors ${panelOpen ? 'bg-purple-600 text-white' : 'bg-gray-800 hover:bg-gray-700 text-gray-300'}`}
      >⚙</button>

      {/* Settings panel */}
      {panelOpen && (
        <div className="absolute top-12 right-3 w-60 bg-gray-900 border border-gray-700 rounded shadow-2xl text-xs z-10 overflow-y-auto max-h-[calc(100%-4rem)]">
          <div className="px-3 py-2 font-semibold text-gray-200 border-b border-gray-700 flex items-center justify-between">
            <span>Graph Settings</span>
            <button onClick={() => setPanelOpen(false)} className="text-gray-500 hover:text-gray-300 leading-none">✕</button>
          </div>

          {/* ── Filters ── */}
          <Section title="Filters">
            <input
              type="text"
              placeholder="Search nodes…"
              value={filters.search}
              onChange={e => setFilter('search', e.target.value)}
              className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-gray-200 placeholder-gray-500 outline-none focus:border-purple-500"
            />
            <Toggle label="Show orphan nodes"  checked={filters.showOrphans}      onChange={v => setFilter('showOrphans', v)} />
            <Toggle label="Show attachments"   checked={filters.showAttachments}  onChange={v => setFilter('showAttachments', v)} />
            <p className="text-gray-500 mt-1">Node types</p>
            {ALL_GROUPS.map(g => (
              <Toggle
                key={g}
                label={
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: nodeColor(g) }} />
                    {g}
                  </span>
                }
                checked={filters.visibleGroups[g] !== false}
                onChange={v => setFilter('visibleGroups', { ...filters.visibleGroups, [g]: v })}
              />
            ))}
          </Section>

          {/* ── Display ── */}
          <Section title="Display">
            <Slider label="Node size"      min={3}   max={14}  step={1}   value={display.nodeSize}       onChange={v => setDisplay_('nodeSize', v)} />
            <Slider label="Link thickness" min={0.5} max={5}   step={0.5} value={display.linkThickness}  onChange={v => setDisplay_('linkThickness', v)} />
            <div className="flex flex-col gap-1">
              <span className="text-gray-400">Labels</span>
              <div className="flex gap-1">
                {['always', 'hover', 'never'].map(m => (
                  <button key={m} onClick={() => setDisplay_('labelMode', m)}
                    className={`flex-1 py-0.5 rounded capitalize ${display.labelMode === m ? 'bg-purple-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}>
                    {m}
                  </button>
                ))}
              </div>
            </div>
            <Toggle label="Show arrows" checked={display.showArrows} onChange={v => setDisplay_('showArrows', v)} />
          </Section>

          {/* ── Forces ── */}
          <Section title="Forces" defaultOpen={false}>
            <Slider label="Repel strength"  min={-600} max={-20}  step={20}   value={forces.repel}         onChange={v => setForce('repel', v)} />
            <Slider label="Link distance"   min={20}   max={300}  step={10}   value={forces.linkDistance}  onChange={v => setForce('linkDistance', v)} />
            <Slider label="Center gravity"  min={0.01} max={0.5}  step={0.01} value={forces.gravity}       onChange={v => setForce('gravity', v)} />
          </Section>
        </div>
      )}
    </div>
  )
}
