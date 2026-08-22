/**
 * Browser gestures that land on the app's own chrome — ⌘R with the address bar
 * focused, a mouse's back/forward buttons over the pane's frame.
 *
 * The interesting case is handled elsewhere: when the user is INSIDE the guest
 * page, main acts on the focused webContents directly (see
 * `commandFocusedGuest`), because a webview guest is out-of-process and nothing
 * in this renderer can see it. This registry only covers the other half — focus
 * sitting in Hermes' own DOM, where `activeElement` is authoritative.
 */

import { $rightRailActiveTabId } from '@/store/layout'
import { $previewTabs } from '@/store/preview'

/** Marks a live browser pane so a gesture can find the one holding focus. */
export const PREVIEW_BROWSER_ATTR = 'data-preview-browser'

/** Which document the pane is showing, and whether it is on the move.
 *
 *  Sampled either side of an agent action so a navigation cannot be reported as
 *  a quiet page. `generation` counts load starts and commits; it is the only
 *  signal that catches a navigation which has BEGUN but not yet swapped the
 *  document, which is exactly what a form submit or a link click looks like at
 *  the moment the act layer re-reads the page. */
export interface PreviewDocState {
  generation: number
  url: string
}

export interface PreviewNavHandle {
  back: () => void
  /** The pane's current document state. Absent on panes that predate it, which
   *  callers treat as "cannot tell" rather than "did not navigate". */
  doc?: () => PreviewDocState
  forward: () => void
  reload: () => void
}

/** The history verbs a gesture or the agent can ask for — the handle's callable
 *  commands, as distinct from `doc`, which reports rather than acts. */
export type PreviewNavCommand = 'back' | 'forward' | 'reload'

const handles = new Map<string, PreviewNavHandle>()

/** Register a live browser pane's commands; returns an idempotent remove. */
export function registerPreviewNav(tabId: string, handle: PreviewNavHandle): () => void {
  handles.set(tabId, handle)

  return () => {
    if (handles.get(tabId) === handle) {
      handles.delete(tabId)
    }
  }
}

/** The ACTIVE preview tab's commands, for callers with no focus to key off —
 *  the agent's drive_preview, which runs while focus is in the composer. */
export function activePreviewNav(): PreviewNavHandle | null {
  const tabs = $previewTabs.get()
  const tab = tabs.find(t => t.id === $rightRailActiveTabId.get()) ?? tabs[0]

  return (tab && handles.get(tab.id)) || null
}

/** Run `command` on the browser pane holding DOM focus. False = focus is
 *  elsewhere in the app, so the caller falls back to the app-level meaning. */
export function commandFocusedPreview(command: PreviewNavCommand): boolean {
  const host = document.activeElement?.closest(`[${PREVIEW_BROWSER_ATTR}]`)
  const nav = host ? handles.get(host.getAttribute(PREVIEW_BROWSER_ATTR) || '') : undefined

  nav?.[command]()

  return Boolean(nav)
}
