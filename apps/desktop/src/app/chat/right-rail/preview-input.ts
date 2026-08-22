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

/** Convert a point the act engine measured into the units input events take.
 *
 *  The engine measures targets with `getBoundingClientRect`, i.e. CSS pixels
 *  INSIDE the zoomed guest page. `sendInputEvent` is a browser-level input
 *  channel whose coordinates are scaled by the page's zoom on the way in. The
 *  relationship was measured live against a page that reports where its
 *  `pointerdown` actually landed:
 *
 *      css_received = dip_sent / zoomFactor
 *
 *  So an unconverted point lands at `1/factor` of where the agent aimed. At
 *  Fares's zoom factor of 1.2220792770385742, a click aimed at a link centred at
 *  CSS (620, 130) arrived at CSS (507, 106) and activated the page container
 *  instead. Inverting that law gives the conversion below — MULTIPLY, so that
 *  `dip / factor` lands back on the CSS point that was aimed at.
 *
 *  Verified against the real Electron input pipeline (a webview at that zoom,
 *  driven by `sendInputEvent`, on a page that reports what its own pointerdown
 *  hit). Sending the raw CSS point hit the container; `css * factor` hit the
 *  link; `css / factor` also hit the container — so the direction here is not a
 *  guess, and getting it backwards is a silent regression, not a type error.
 *
 *  The failure was invisible because the read-back rides the separate script
 *  channel and saw a perfectly healthy page, so every mis-aimed click was
 *  reported as a success. A zoom of exactly 1 is the identity — measured: at
 *  factor 1 all three candidate laws hit — which is why this went unnoticed
 *  until someone zoomed the app. */
export function toInputPoint(point: DrivePointLike, factor: number): DrivePointLike {
  // A missing or nonsense factor means unzoomed rather than a poisoned point:
  // sending NaN would put the click at an unpredictable spot, which is worse
  // than not scaling it.
  const scale = Number.isFinite(factor) && factor > 0 ? factor : 1

  return { x: Math.round(point.x * scale), y: Math.round(point.y * scale) }
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
