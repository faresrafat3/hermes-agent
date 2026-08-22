import { readActivePreview } from '@/app/chat/right-rail/preview-reader'
import { writeAgentTerminalChunk } from '@/app/right-sidebar/terminal/agent-terminal-stream'
import { readActiveTerminal } from '@/app/right-sidebar/terminal/buffer'
import { closeAgentTerminalByProc } from '@/app/right-sidebar/terminal/terminals'
import type { GatewayEventPayload } from '@/lib/chat-messages'
import type { PreviewActAction } from '@/lib/preview-act/act-in-page'
import type { TourAction, TourStep } from '@/lib/tour'
import { $gateway } from '@/store/gateway'
import { applyDesktopLayoutPreset, revealDesktopPane } from '@/store/pane-focus'
import { recordAgentReaction } from '@/store/reactions-local'
import { setMessages } from '@/store/session'

import type { GatewayEventContext } from './types'

/** The preview engine, loaded on demand so ~25KB of page-injectable source stays
 *  off the boot path.
 *
 *  In dev that lazy chunk is also a trap. The browser caches a dynamic import by
 *  URL for the life of the page, so this bridge would hand every action to
 *  whichever build of the engine loaded first, and no edit to it — or to the
 *  overlay whose source it stringifies into the page — would reach the guest
 *  until the whole window reloaded. Asking for a fresh copy is more reliable
 *  than trusting hot-update propagation to reach a module nothing statically
 *  imports; the dev server stamps the dependency URLs it has invalidated, so a
 *  fresh engine pulls a fresh overlay down with it.
 *
 *  The literal path is what a bare specifier can't be here, and it has to track
 *  this module's real location — hence the fall back to the static import, which
 *  is also the only branch production keeps, `import.meta.hot` being stripped
 *  there along with everything it guards. */
const loadPreviewEngine = () => {
  const stable = () => import('@/app/chat/right-rail/preview-act')

  if (!import.meta.hot) {
    return stable().then(mod => mod.actOnActivePreview)
  }

  return import(/* @vite-ignore */ '/src/app/chat/right-rail/preview-act.ts?hot=' + Date.now())
    .catch(stable)
    .then(mod => mod.actOnActivePreview as Awaited<ReturnType<typeof stable>>['actOnActivePreview'])
}

/** Translate one `preview.act.request` into the engine's action.
 *
 *  Extracted so the mapping is testable on its own: the bridge forwards fields
 *  ONE BY ONE, so a parameter missing from this object is silently dropped on
 *  the wire — the tool accepts it, the gateway relays it, and the engine never
 *  sees it. That is exactly how `full` was lost: `elements` with `full: true`
 *  kept answering with a delta, leaving the agent no way to re-establish a
 *  baseline for a page it had lost track of.
 *
 *  Absent fields stay `undefined` rather than getting a bridge-invented default,
 *  so the engine's own defaults remain the single source of that policy. */
export function previewActionFromPayload(
  payload: GatewayEventPayload | undefined
): Omit<PreviewActAction, 'kind'> & { kind: string } {
  return {
    amount: payload?.amount,
    full: payload?.full,
    key: payload?.key,
    kind: payload?.action ?? '',
    max: payload?.max,
    ref: payload?.ref,
    selector: payload?.selector,
    submit: payload?.submit,
    text: payload?.text,
    to: payload?.to as PreviewActAction['to']
  }
}

/** Whether a desktop-surface bridge request may run for the session that sent
 *  it, given whether that session is the one on screen.
 *
 *  The distinction is what the request DOES, not which chat is in the
 *  foreground:
 *
 *  - `tour.request` PAINTS on the user's screen (driver.js overlays) and
 *    `pane.focus` / layout presets rearrange the window, so a background turn
 *    doing either would seize a screen the user is using elsewhere. Those stay
 *    foreground-only (desktop AGENTS.md: "Isolate the foreground").
 *  - `preview.act.request` acts on the preview pane, which is WINDOW-scoped:
 *    its tabs and active-tab id live in window-level stores, not in any session.
 *    Nothing is published into the chat view, so the foreground rule does not
 *    apply -- and gating it broke the ordinary case of leaving the browser open
 *    in the side pane, asking one session to work in it, and switching chats
 *    while it runs. `preview.read.request` never had the gate, so reads worked
 *    while clicks on the same page were refused.
 *
 *  Exported as data so the contract is testable and lives in one place. */
export function bridgeRequestAllowed(eventType: string, isActiveEvent: boolean): boolean {
  return FOREGROUND_ONLY_BRIDGE_EVENTS.has(eventType) ? isActiveEvent : true
}

/** Requests that put something on the user's screen, and so must not run for a
 *  session the user is not looking at. */
const FOREGROUND_ONLY_BRIDGE_EVENTS = new Set(['tour.request'])

/** Desktop-surface bridge events: read-back requests the agent blocks on
 *  (terminal/preview/window), agent terminal streaming, pane reveal, and
 *  message reactions. */
export function handleDesktopBridgeEvent(ctx: GatewayEventContext): boolean {
  const { event, payload, isActiveEvent } = ctx

  if (event.type === 'terminal.read.request') {
    // read_terminal tool: serialize the renderer's xterm buffer and answer
    // immediately (Python blocks on the respond). Empty text = no live pane.
    const requestId = typeof payload?.request_id === 'string' ? payload.request_id : ''

    if (requestId) {
      const start = typeof payload?.start === 'number' ? payload.start : undefined
      const count = typeof payload?.count === 'number' ? payload.count : undefined
      const result = readActiveTerminal({ start, count })

      void $gateway.get()?.request('terminal.read.respond', {
        request_id: requestId,
        text: result ? JSON.stringify(result) : ''
      })
    }

    return true
  }

  if (event.type === 'preview.read.request') {
    // read_preview tool: serialize the active preview tab (a Browser
    // webview's page text is async) and answer. Empty text = nothing open.
    const requestId = typeof payload?.request_id === 'string' ? payload.request_id : ''

    if (requestId) {
      const start = typeof payload?.start === 'number' ? payload.start : undefined
      const count = typeof payload?.count === 'number' ? payload.count : undefined

      void readActivePreview({ count, start }).then(result => {
        void $gateway.get()?.request('preview.read.respond', {
          request_id: requestId,
          text: result ? JSON.stringify(result) : ''
        })
      })
    }

    return true
  }

  if (event.type === 'preview.act.request') {
    // drive_preview tool: click/type/scroll/press inside the guest page, or
    // drive the pane's history. Dynamic import keeps the injected engine off
    // the boot path.
    //
    // NOT gated on the routed session being the one on screen. The preview pane
    // is WINDOW-scoped -- its tabs and active-tab id live in window-level
    // stores, not in any session -- so "which chat is in the foreground" says
    // nothing about whether this request may touch it. Gating on it broke the
    // ordinary case: the user leaves the browser open in the side pane, asks one
    // session to work in it, then switches to another chat while it runs, and
    // every action from then on failed with "only takes actions in the session
    // the user is looking at" -- about a pane still sitting right there. The
    // companion preview.read.request above never had the gate, so reads
    // succeeded while clicks were refused on the very same page, which is the
    // tell that the gate was guarding the wrong noun.
    //
    // What the foreground rule protects is PUBLISHING into the view the user is
    // looking at (desktop AGENTS.md: "Isolate the foreground"), and this path
    // publishes nothing: it acts on the pane and answers the blocked tool.
    const requestId = typeof payload?.request_id === 'string' ? payload.request_id : ''

    if (requestId) {
      const answer = (result: unknown) =>
        $gateway.get()?.request('preview.act.respond', {
          request_id: requestId,
          text: result ? JSON.stringify(result) : ''
        })

      void loadPreviewEngine()
        .then(run => run(previewActionFromPayload(payload)))
        .then(answer, error =>
          answer({ error: error instanceof Error ? error.message : String(error), success: false })
        )
    }

    return true
  }

  if (event.type === 'window.read.request') {
    // read_window_below tool: main owns native window enumeration, so ask
    // it over IPC and answer. Empty text = unavailable (no bridge, or
    // enumeration unsupported on this system e.g. Wayland).
    const requestId = typeof payload?.request_id === 'string' ? payload.request_id : ''

    if (requestId) {
      const read = window.hermesDesktop?.readWindowBelow

      const answer = (result: unknown) =>
        $gateway.get()?.request('window.read.respond', {
          request_id: requestId,
          text: result ? JSON.stringify(result) : ''
        })

      // .catch: ipcRenderer.invoke rejects on an older shell without the
      // handler or a main-side throw — without an empty answer the tool
      // would stall its full 30s timeout.
      void Promise.resolve(read ? read() : null).then(answer, () => answer(null))
    }

    return true
  }

  if (event.type === 'agent.terminal.output') {
    // Live chunk from a background process → its read-only agent terminal tab.
    writeAgentTerminalChunk(payload?.process_id ?? '', payload?.chunk ?? '')

    return true
  }

  if (event.type === 'terminal.close') {
    // Agent closed its own read-only tab via the desktop-gated close_terminal tool.
    // The process is untouched — this only drops the view.
    closeAgentTerminalByProc(payload?.process_id ?? '')

    return true
  }

  if (event.type === 'tour.request') {
    // tour tool: run one guided-tour action (highlight/step/discover) via
    // driver.js — on the app's own DOM or inside the preview pane's guest
    // page — and answer with the outcome. Dynamic import keeps driver.js
    // and the preview injection payload off the boot path. Active session
    // only: a background turn must never paint overlays on the user's
    // screen (desktop AGENTS.md: offer, don't hijack).
    const requestId = typeof payload?.request_id === 'string' ? payload.request_id : ''

    if (requestId) {
      const answer = (result: unknown) =>
        $gateway.get()?.request('tour.respond', {
          request_id: requestId,
          text: result ? JSON.stringify(result) : ''
        })

      if (bridgeRequestAllowed(event.type, isActiveEvent)) {
        void import('@/lib/tour')
          .then(({ runTour }) =>
            runTour(
              {
                kind: (payload?.action ?? 'stop') as TourAction['kind'],
                selector: payload?.selector,
                side: payload?.side as TourStep['side'],
                startAt: payload?.step_index,
                steps: payload?.steps as TourStep[] | undefined,
                text: payload?.text,
                title: payload?.title
              },
              payload?.surface === 'preview' ? 'preview' : 'app'
            )
          )
          .then(answer, error =>
            answer({ error: error instanceof Error ? error.message : String(error), success: false })
          )
      } else {
        void answer({
          error: 'Tours only run in the session the user is looking at.',
          success: false
        })
      }
    }

    return true
  }

  if (event.type === 'pane.reveal') {
    // Agent revealed a pane via the desktop-gated focus_pane tool, in
    // response to an explicit user request. Active session only — a
    // background turn must never move the user's focus (desktop AGENTS.md:
    // offer, don't hijack).
    if (isActiveEvent) {
      revealDesktopPane(payload?.pane ?? '')
    }

    return true
  }

  if (event.type === 'layout.apply') {
    // Agent applied a layout preset via the desktop-gated apply_layout
    // tool. Same contract as pane.reveal: active session only, and the
    // preset resolves against the SAME layouts registry the picker reads,
    // so core, plugin, and user presets are all addressable.
    if (isActiveEvent) {
      applyDesktopLayoutPreset(typeof payload?.preset === 'string' ? payload.preset : '')
    }

    return true
  }

  if (event.type === 'message.reaction') {
    // The agent reacted to a message via the desktop-gated
    // react_to_message tool. Already persisted — this only paints it now
    // instead of at the next resume. Fresh ChatMessage object per change:
    // the runtime repository caches normalized ThreadMessages in a WeakMap
    // keyed by ChatMessage identity.
    const reactedRowId = payload?.row_id

    if (typeof reactedRowId === 'number') {
      const nextReactions = Array.isArray(payload?.reactions) ? payload.reactions : []
      const reactedRole = payload?.role === 'assistant' ? 'assistant' : 'user'

      setMessages(messages => {
        // Preferred leg: the message already knows its durable row id
        // (rehydrated transcript, or a live row that has round-tripped).
        const byRowId = messages.find(message => message.rowId === reactedRowId)

        if (byRowId) {
          // Overlay survives the end-of-turn resume, which rebuilds from
          // in-memory history that doesn't carry this mid-turn DB write.
          recordAgentReaction(reactedRowId, nextReactions)

          return messages.map(message =>
            message.rowId === reactedRowId ? { ...message, reactions: nextReactions } : message
          )
        }

        // Live leg: the targeted message is still optimistic (no rowId —
        // it hasn't round-tripped through a resume). The agent's default
        // target is the newest message of that role, so stamp the reaction
        // AND the now-known row id onto it. Without this the event matches
        // nothing and the reaction only appears after a reload.
        const lastIndex = messages.findLastIndex(message => message.role === reactedRole && message.rowId === undefined)

        if (lastIndex === -1) {
          return messages
        }

        recordAgentReaction(reactedRowId, nextReactions)

        return messages.map((message, index) =>
          index === lastIndex ? { ...message, rowId: reactedRowId, reactions: nextReactions } : message
        )
      })
    }

    return true
  }

  return false
}
