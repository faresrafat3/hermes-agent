/**
 * PREVIEW INPUT REGISTRY — real input into the preview pane's guest page, the
 * difference between the agent DRIVING the browser and merely poking its DOM.
 *
 * `executeJavaScript` can only ever dispatch synthetic events: `isTrusted` is
 * false, the browser's own hover target never moves, `:hover` rules never
 * match, and hover-gated menus never open — so a click lands on a dropdown item
 * that was never rendered. `sendInputEvent` goes in through Chromium's input
 * pipeline instead, producing the same events a hand on the mouse would.
 *
 * It has to be called on the `<webview>` ELEMENT. Sending to the embedder's
 * webContents does not reach a guest (electron/electron#20333), which is why
 * this is a per-pane registry rather than something main could do.
 *
 * Coordinates are relative to the webview, and the webview IS the guest
 * viewport — so a rect the act engine measured inside the page needs no
 * conversion on the way back out.
 */

import { $rightRailActiveTabId } from '@/store/layout'
import { $previewTabs } from '@/store/preview'

/** The subset of Electron's input events the agent needs to drive a page. */
export type PreviewInputEvent =
  | { button: 'left'; clickCount: number; type: 'mouseDown' | 'mouseUp'; x: number; y: number }
  | { deltaX: number; deltaY: number; type: 'mouseWheel'; x: number; y: number }
  | { keyCode: string; modifiers?: string[]; type: 'char' | 'keyDown' | 'keyUp' }
  | { type: 'mouseMove'; x: number; y: number }

export interface PreviewInputHandle {
  /** Give the guest keyboard focus, so key events reach its active element. */
  focus: () => void
  send: (event: PreviewInputEvent) => void
  /** Guest CSS pixels per device-independent pixel (the guest's zoom factor),
   *  read live at send time. Absent on a pane that cannot report it, which the
   *  conversion treats as unzoomed. */
  zoom?: () => number
}

/** Guest CSS pixels per device-independent pixel — the guest's zoom factor.
 *
 *  The act engine measures targets with `getBoundingClientRect`, which is CSS
 *  pixels INSIDE the zoomed page, but `sendInputEvent` is a browser-level input
 *  channel and takes device-independent pixels. At any zoom but 100% those two
 *  units differ, so an unconverted point lands at `1/factor` of where the agent
 *  aimed: measured live at zoom 1.222, a click aimed at (620, 130) arrived at
 *  (507, 106) and hit the container instead of the link. Every click, type and
 *  wheel was landing in the wrong place, and the failure was invisible because
 *  the read-back rode the separate script channel and still reported success.
 *
 *  A zoom of exactly 1 (the default) is the identity, which is why this went
 *  unnoticed until someone zoomed the app. */
export function toDeviceIndependent(point: DrivePointLike, factor: number): DrivePointLike {
  // A missing or nonsense factor means unzoomed rather than a poisoned point:
  // dropping the input entirely would be a worse failure than not scaling it.
  const scale = Number.isFinite(factor) && factor > 0 ? factor : 1

  return { x: Math.round(point.x / scale), y: Math.round(point.y / scale) }
}

/** Just the coordinate pair, so this module needn't import the drive types. */
export interface DrivePointLike {
  x: number
  y: number
}

const handles = new Map<string, PreviewInputHandle>()

/** Register a live pane's input channel; returns an idempotent unregister. */
export function registerPreviewInput(tabId: string, handle: PreviewInputHandle): () => void {
  handles.set(tabId, handle)

  return () => {
    if (handles.get(tabId) === handle) {
      handles.delete(tabId)
    }
  }
}

/** The ACTIVE preview tab's input channel. Null = nothing real to drive, and
 *  the caller falls back to synthesizing events inside the page. */
export function activePreviewInput(): PreviewInputHandle | null {
  const tabs = $previewTabs.get()
  const tab = tabs.find(t => t.id === $rightRailActiveTabId.get()) ?? tabs[0]

  return (tab && handles.get(tab.id)) || null
}
