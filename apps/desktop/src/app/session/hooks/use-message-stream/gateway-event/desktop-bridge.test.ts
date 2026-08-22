import { describe, expect, it } from 'vitest'

import type { GatewayEventPayload } from '@/lib/chat-messages'

import { bridgeRequestAllowed, previewActionFromPayload } from './desktop-bridge'

/**
 * The bridge translates a `preview.act.request` into the engine's action by
 * listing fields ONE BY ONE, so a parameter it forgets is silently dropped on
 * the wire: the tool accepts the argument, the gateway relays it, and the engine
 * never sees it. Nothing fails — the agent just gets an answer to a different
 * question.
 *
 * That is how `full` was lost. `drive_preview(action='elements', full=true)`
 * kept answering with a delta, so an agent that had lost track of a page had no
 * way to ask for a fresh baseline. Caught live on console.x.com.
 */
const request = (payload: Partial<GatewayEventPayload>) => payload as GatewayEventPayload

describe('previewActionFromPayload', () => {
  it('forwards full, so an inventory request is not answered with a delta', () => {
    expect(previewActionFromPayload(request({ action: 'elements', full: true }))).toMatchObject({
      full: true,
      kind: 'elements'
    })
  })

  it('forwards every argument drive_preview can send', () => {
    // The whole documented surface at once: a field the bridge drops shows up
    // here as undefined. Asserted with toEqual so an omission cannot hide.
    const action = previewActionFromPayload(
      request({
        action: 'type',
        amount: 400,
        full: true,
        key: 'Enter',
        max: 25,
        ref: 'inp-email',
        selector: '#email',
        submit: true,
        text: 'hello',
        to: 'bottom'
      })
    )

    expect(action).toEqual({
      amount: 400,
      full: true,
      key: 'Enter',
      kind: 'type',
      max: 25,
      ref: 'inp-email',
      selector: '#email',
      submit: true,
      text: 'hello',
      to: 'bottom'
    })
  })

  it('leaves absent arguments undefined rather than inventing defaults', () => {
    const action = previewActionFromPayload(request({ action: 'elements' }))

    // A delta IS the right answer for a caller that did not ask for a full
    // read — but that policy belongs to the engine. A bridge-invented
    // `full: false` would be a second place to change it.
    expect(action.full).toBeUndefined()
    expect(action.max).toBeUndefined()
    expect(action.kind).toBe('elements')
  })

  it('survives a payload that never arrived', () => {
    // The bridge runs before it knows the request is well-formed; an empty verb
    // is rejected downstream by the tool's own enum check.
    expect(previewActionFromPayload(undefined).kind).toBe('')
  })
})

/**
 * The preview pane is WINDOW-scoped: its tabs and active-tab id live in
 * window-level stores, not in any session. Gating agent interaction on "is this
 * chat in the foreground" therefore guarded the wrong noun, and it broke the
 * ordinary case Fares actually works in — browser left open in the side pane,
 * one session told to work in it, then switching chats while it runs. Every
 * action from that point failed with "only takes actions in the session the user
 * is looking at", about a pane still sitting right there. `preview.read.request`
 * never had the gate, so reads succeeded while clicks on the same page were
 * refused: same page, same window, two different answers.
 *
 * What the foreground rule protects is painting/publishing into the view the
 * user is looking at, which is why the tour keeps its gate.
 */
describe('bridgeRequestAllowed', () => {
  it('lets the agent drive the preview pane from a background session', () => {
    // The regression. A pane the user can see is not the property of whichever
    // chat happens to be on screen.
    expect(bridgeRequestAllowed('preview.act.request', false)).toBe(true)
  })

  it('lets it drive the pane from the foreground session too', () => {
    expect(bridgeRequestAllowed('preview.act.request', true)).toBe(true)
  })

  it('keeps reads ungated, matching the interaction path', () => {
    // The inconsistency that revealed the bug: these two must agree, because
    // they address the very same page in the very same window.
    for (const active of [true, false]) {
      expect(bridgeRequestAllowed('preview.read.request', active)).toBe(
        bridgeRequestAllowed('preview.act.request', active)
      )
    }
  })

  it('still refuses to paint a tour over a session the user is not watching', () => {
    // Overlays land on the user's screen, so this one genuinely is foreground
    // work — the gate belongs here, not on the pane.
    expect(bridgeRequestAllowed('tour.request', false)).toBe(false)
    expect(bridgeRequestAllowed('tour.request', true)).toBe(true)
  })
})
