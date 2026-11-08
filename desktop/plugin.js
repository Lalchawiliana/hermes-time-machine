import React, { useEffect, useState, useCallback } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'
import { host } from '@hermes/plugin-sdk'

const h = React.createElement
const btn = 'rounded-md border border-(--ui-stroke-secondary) px-2.5 py-1.5 text-xs hover:bg-(--ui-bg-hover) disabled:opacity-40'
const card = 'rounded-lg border border-(--ui-stroke-secondary) p-3'

function Timeline({ api }) {
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState('')
  const [diff, setDiff] = useState(null)
  const [error, setError] = useState('')
  const [working, setWorking] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const refresh = useCallback(async () => {
    try {
      const s = await api.rest('/status')
      setData(s)
      setError(s.error || '')
    } catch (e) { setError(String(e)) }
  }, [api])
  useEffect(() => {
    refresh()
    // React cleanup on plugin disable + pane unmount
    const t = setInterval(refresh, 3500)
    return () => clearInterval(t)
  }, [refresh])
  useEffect(() => {
    if (!selected) return
    let active = true
    api.rest('/diff/' + encodeURIComponent(selected)).then(v => { if (active) setDiff(v) }).catch(e => { if (active) setError(String(e)) })
    return () => { active = false }
  }, [selected, api, data?.fingerprint])
  async function checkpoint() {
    setWorking(true)
    try { await api.rest('/checkpoint', { method: 'POST', body: {} }); await refresh() }
    catch (e) { setError(String(e)) }
    finally { setWorking(false) }
  }
  async function restore() {
    if (!selected || !diff) return
    const count = diff.changes?.length || 0
    if (!confirming) { setConfirming(true); return }
    setConfirming(false)
    setWorking(true)
    try {
      await api.rest('/restore', { method: 'POST', body: { checkpoint_id: selected, fingerprint: diff.fingerprint, confirm: true } })
      await refresh()
      host.notify({ kind: 'success', message: 'Protected workspace restored. Conversation state was not changed.' })
    } catch (e) { setError('Restore rejected: ' + String(e)); await refresh() }
    finally { setWorking(false) }
  }
  if (!data) return h('div', {className:'p-4 text-sm',children:'Connecting to Time-Machine…'})
  const points = data.checkpoints || []
  const events = data.events || []
  return h('div', { className: 'h-full overflow-auto p-4 space-y-3 text-sm', children: [
    h('header', { key:'hd', className:'flex items-center justify-between', children: [
      h('div',{children:[h('div',{className:'text-base font-semibold',children:'⏪ Time-Machine'}), h('div',{className:'text-xs text-(--ui-text-tertiary)',children:'Your workspace flight recorder'})]}),
      h('button',{className:btn,disabled:working,onClick:refresh,children:'Refresh'})
    ]}),
    h('div',{key:'s',className:card,children:[
      h('div',{className:'font-medium',children:data.protected && data.docker_ready ? '● Docker ready' : '● Protection unavailable'}),
      h('div',{className:'text-xs text-(--ui-text-tertiary) break-all',children:data.workspace || 'Workspace not configured'}),
      h('div',{className:'text-xs text-(--ui-text-tertiary)',children:data.docker_status || 'No Docker status'}),
      h('button',{className:btn+' mt-2',disabled:working || !data.protected,onClick:checkpoint,children:'Create checkpoint'})
    ]}),
    error && h('div',{key:'err',role:'alert',className:'rounded border p-2 text-xs text-(--ui-danger)',children:error}),
    h('section',{key:'p',className:card,children:[
      h('h3',{className:'font-semibold mb-2',children:`Checkpoints (${points.length})`}),
      points.length===0 ? h('div',{className:'text-xs text-(--ui-text-tertiary)',children:'No checkpoints yet.'}) :
      h('div',{className:'flex flex-col gap-1 max-h-56 overflow-auto',children:points.map(p=>h('button',{key:p.id,
        onClick:()=>{setSelected(p.id);setDiff(null);setConfirming(false)}, className:'text-left rounded px-2 py-1.5 border border-(--ui-stroke-secondary)',
        style:{outline:selected===p.id?'2px solid var(--ui-accent)':'none'},
        children:[h('div',{className:'text-xs font-medium',children:p.label}),h('div',{className:'text-[11px] text-(--ui-text-tertiary)',children:new Date(p.created*1000).toLocaleTimeString()+' · '+p.id.slice(0,8)})]
      }))})
    ]}),
    selected && h('section',{key:'diff',className:card,children:[
      h('h3',{className:'font-semibold',children:'Workspace changes vs selected checkpoint'}),
      h('div',{className:'mt-2 max-h-52 overflow-auto space-y-1',children:(diff?.changes || []).map(c=>h('div',{key:c.path,className:'text-xs break-all',children:`${c.status==='deleted'?'+':c.status==='added'?'-':'~'} ${c.path} (${c.status})`}))}),
      h('div',{className:'text-xs text-(--ui-text-tertiary)',children:diff ? `${diff.changes.length} tracked file differences. Restore creates a pre-restore backup.` : 'Loading diff…'}),
      h('button',{className:btn+' mt-3',disabled:working||!diff,onClick:restore,children:confirming?'CONFIRM: Overwrite tracked files':'Restore this checkpoint…'})
    ]}),
    h('section',{key:'e',className:card,children:[
      h('h3',{className:'font-semibold mb-2',children:'Execution events'}),
      h('div',{className:'max-h-40 overflow-auto space-y-2',children:events.slice(0,12).map(e=>h('div',{key:e.id,className:'text-xs border-l-2 pl-2 border-(--ui-stroke-secondary)',children:`${e.status.toUpperCase()} · ${e.tool} · ${e.elapsed_ms}ms · ${new Date(e.created*1000).toLocaleTimeString()}`}))})
    ]}),
    h('p',{key:'c',className:'text-[11px] text-(--ui-text-tertiary)',children:'Only tracked workspace files can be restored. Excluded paths, external services, and Hermes conversation history are not rewound.'})
  ]})
}

export default {
  id: 'hermes-time-machine',
  name: 'Hermes Time-Machine',
  defaultEnabled: false,
  register(ctx) {
    const api = { rest: (...args) => ctx.rest(...args) }
    ctx.register({ id:'timeline', area:'panes', title:'Time-Machine', data:{placement:'right',width:'360px'}, render:()=>jsx(Timeline,{api}) })
    ctx.register({ id:'open', area:'palette', data:{id:'time-machine.open',label:'Open Time-Machine',keywords:['rollback','checkpoint','time machine'],run:()=>host.notify({kind:'info',message:'Open the Time-Machine pane in your workspace layout.'})} })
  }
}