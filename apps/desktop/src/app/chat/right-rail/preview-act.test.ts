import { beforeEach, describe, expect, it, vi } from 'vitest'

import { $rightRailActiveTabId } from '@/store/layout'
import { closeRightRail, openPreview, type PreviewTarget } from '@/store/preview'

import { actOnActivePreview } from './preview-act'
import { registerPreviewInput } from './preview-input'
import { registerPreviewNav } from './preview-nav'
import { registerPreviewScriptRunner } from './preview-script-runner'

function urlTarget(url: string): PreviewTarget {
  return { kind: 'url', label: 'Browser', source: url, url }
}

describe('actOnActivePreview (drive_preview tool)', () => {
  // URL targets share the singleton Browser tab id, so anything a test
  // registers would answer the next one.
  let cleanups: Array<() => void> = []

  const openBrowserTab = () => {
    openPreview(urlTarget('https://example.com'), 'tool-result')

    return $rightRailActiveTabId.get()!
  }

  const withRunner = (runner: (code: string) => Promise<unknown>) =>
    cleanups.push(registerPreviewScriptRunner(openBrowserTab(), runner))

  beforeEach(() => {
    vi.useRealTimers()

    for (const cleanup of cleanups) {
      cleanup()
    }

    cleanups = []
    closeRightRail()
    window.localStorage.clear()
  })

  it('tells the agent to open a page when no live pane is behind the tab', async () => {
    const result = await actOnActivePreview({ kind: 'elements' })

    expect(result.success).toBe(false)
    expect(result.error).toContain('open_preview')
  })

  it('injects the engine and returns the page’s answer', async () => {
    let injected = ''

    withRunner(async code => {
      injected = code

      return JSON.stringify({ acted: 'clicked button "Save"', success: true })
    })

    const result = await actOnActivePreview({ kind: 'click', ref: '@e1' })

    expect(result).toMatchObject({ acted: 'clicked button "Save"', success: true })
    // Self-contained payload: the engine source and the action travel together,
    // and the holder keeps refs alive across calls on the same page.
    expect(injected).toContain('__hermesActHolder')
    expect(injected).toContain('"ref":"@e1"')
  })

  it('re-inventories after a mutating action so the next ref is current', async () => {
    const actions: string[] = []

    withRunner(code => {
      // Stand in for the guest page: run the script's own settle/rescan shape
      // by answering each act() call in order.
      actions.push(...(code.match(/"kind":"(\w+)"/g) ?? []))

      return Promise.resolve(
        JSON.stringify({
          acted: 'clicked',
          elements: [{ label: 'Log out', ref: '@e1', role: 'button', selector: '#out' }],
          success: true,
          url: 'https://example.com/app'
        })
      )
    })

    const result = await actOnActivePreview({ kind: 'click', ref: '@e1' })

    expect(result.elements?.[0].label).toBe('Log out')
    expect(result.url).toBe('https://example.com/app')
  })

  it('does not pay the settle delay for a plain inventory', async () => {
    let injected = ''
    withRunner(async code => {
      injected = code

      return JSON.stringify({ elements: [], success: true })
    })

    await actOnActivePreview({ kind: 'elements' })

    expect(injected).toContain('0 <= 0')
  })

  it('reports a page that answers with nothing', async () => {
    withRunner(async () => '')

    expect((await actOnActivePreview({ kind: 'click', ref: '@e1' })).error).toContain('did not answer')
  })

  /** A pane that answers the locate trip with a fixed on-screen point, and the
   *  read-back trip with an empty inventory. Returns the input spy. */
  const withDrivenPane = () => {
    const tabId = openBrowserTab()
    const send = vi.fn()

    cleanups.push(
      registerPreviewScriptRunner(tabId, async code =>
        code.includes('"kind":"locate"')
          ? JSON.stringify({ acted: 'looking at button "Save"', point: { x: 120, y: 80 }, success: true })
          : // `hit` is the page's witness that the real pointerdown arrived.
            JSON.stringify({ elements: [], hit: { tag: 'BUTTON', trusted: true }, success: true })
      )
    )
    cleanups.push(registerPreviewInput(tabId, { focus: vi.fn(), send }))

    return send
  }

  const sentTypes = (send: ReturnType<typeof vi.fn>) => send.mock.calls.map(([event]) => event.type)

  it('clicks with real input, walking the pointer to where the page said', async () => {
    const send = withDrivenPane()

    const result = await actOnActivePreview({ kind: 'click', ref: '@e1' })
    const types = sentTypes(send)

    // Stepped rather than teleported: a page learns it is hovered from a stream
    // of moves, and one jump to the target skips everything in between.
    expect(types.filter(type => type === 'mouseMove').length).toBeGreaterThan(1)
    expect(types).toContain('mouseDown')
    expect(types).toContain('mouseUp')
    expect(send.mock.calls.map(([event]) => event).find(event => event.type === 'mouseDown')).toMatchObject({
      x: 120,
      y: 80
    })
    expect(result.acted).toBe('clicked button "Save"')
  })

  it('types by pressing keys, after selecting whatever the field held', async () => {
    const send = withDrivenPane()

    await actOnActivePreview({ kind: 'type', ref: '@e1', submit: true, text: 'hi' })

    const events = send.mock.calls.map(([event]) => event)
    const chars = events.filter(event => event.type === 'char').map(event => event.keyCode)

    // One click to focus, then select-all by keyboard — NOT the triple-click
    // this used to do. A triple-click is a pointer gesture, so it grabs the
    // paragraph under the cursor whenever the target turns out not to be a
    // field, and the agent was leaving pages with their body text highlighted.
    expect(events.filter(event => event.type === 'mouseDown').map(event => event.clickCount)).toEqual([1])
    expect(events.filter(event => event.type === 'keyDown' && event.keyCode === 'a')[0]).toMatchObject({
      modifiers: ['control', 'meta']
    })
    // The chord must not send a `char` phase, or select-all types a literal 'a'.
    expect(chars).toEqual(['h', 'i', 'Enter'])
  })

  it('hovers by walking the pointer over and leaving it there', async () => {
    const send = withDrivenPane()

    const result = await actOnActivePreview({ kind: 'hover', ref: '@e1' })
    const types = sentTypes(send)

    expect(types).toContain('mouseMove')
    // The whole request is "be on it" — a click here would open the dropdown the
    // agent was trying to reveal, or worse, activate it.
    expect(types).not.toContain('mouseDown')
    expect(result.acted).toBe('hovered over button "Save"')
  })

  // The witness only speaks for verbs that put the button down. Demanding one
  // from a key press reported every press as a failure.
  it('does not expect a click witness from a verb that never clicks', async () => {
    const tabId = openBrowserTab()

    cleanups.push(
      registerPreviewScriptRunner(tabId, async code =>
        code.includes('"kind":"locate"')
          ? JSON.stringify({ acted: 'looking at textbox "Search"', point: { x: 40, y: 20 }, success: true })
          : JSON.stringify({ elements: [], hit: null, success: true })
      )
    )
    cleanups.push(registerPreviewInput(tabId, { focus: vi.fn(), send: vi.fn() }))

    for (const action of [
      { key: 'Escape', kind: 'press', ref: '@e1' },
      { kind: 'hover', ref: '@e1' }
    ]) {
      expect(await actOnActivePreview(action)).toMatchObject({ success: true })
    }
  })

  it('scrolls by wheeling for real, not by scripting the page', async () => {
    const tabId = openBrowserTab()
    const send = vi.fn()
    let scripted = false

    cleanups.push(
      registerPreviewScriptRunner(tabId, async code => {
        scripted ||= code.includes('"kind":"scroll"')

        return code.includes('scrollHeight')
          ? JSON.stringify({ page: 700, point: { x: 500, y: 400 }, span: 4_000, success: true })
          : JSON.stringify({ elements: [], success: true })
      })
    )
    cleanups.push(registerPreviewInput(tabId, { focus: vi.fn(), send }))

    await actOnActivePreview({ kind: 'scroll' })

    const wheels = send.mock.calls.map(([event]) => event).filter(event => event.type === 'mouseWheel')

    // A stream of notches, not one delta: scroll-linked headers and lazy loaders
    // only react to the events, so a scripted scrollBy leaves them asleep.
    expect(wheels.length).toBeGreaterThan(1)
    // Electron's wheel delta is wheelDelta-signed, so scrolling DOWN is negative.
    expect(wheels.every(event => event.deltaY < 0)).toBe(true)
    expect(scripted).toBe(false)
  })

  it('says so plainly when the page has nothing to scroll', async () => {
    const tabId = openBrowserTab()

    cleanups.push(
      registerPreviewScriptRunner(tabId, async () =>
        JSON.stringify({ page: 700, point: { x: 500, y: 400 }, span: 0, success: true })
      )
    )
    cleanups.push(registerPreviewInput(tabId, { focus: vi.fn(), send: vi.fn() }))

    expect(await actOnActivePreview({ kind: 'scroll' })).toMatchObject({
      note: expect.stringContaining('nothing to scroll')
    })
  })

  it('fails loudly when the pointer input never reaches the page', async () => {
    const tabId = openBrowserTab()

    cleanups.push(
      registerPreviewScriptRunner(tabId, async code =>
        code.includes('"kind":"locate"')
          ? JSON.stringify({ acted: 'looking at button "Save"', point: { x: 12, y: 8 }, success: true })
          : JSON.stringify({ elements: [], hit: null, success: true })
      )
    )
    cleanups.push(registerPreviewInput(tabId, { focus: vi.fn(), send: vi.fn() }))

    const result = await actOnActivePreview({ kind: 'click', ref: '@e1' })

    // Everything else about this action travels on the script channel and would
    // report success whether or not a single event landed.
    expect(result.success).toBe(false)
    expect(result.error).toContain('never reached the page')
  })

  it('says so when the overlay itself swallowed the click', async () => {
    const tabId = openBrowserTab()

    cleanups.push(
      registerPreviewScriptRunner(tabId, async code =>
        code.includes('"kind":"locate"')
          ? JSON.stringify({ acted: 'looking at button "Save"', point: { x: 12, y: 8 }, success: true })
          : JSON.stringify({ elements: [], hit: { tag: 'HERMES-WATCH', trusted: true }, success: true })
      )
    )
    cleanups.push(registerPreviewInput(tabId, { focus: vi.fn(), send: vi.fn() }))

    expect((await actOnActivePreview({ kind: 'click', ref: '@e1' })).note).toContain('overlay intercepted')
  })

  it('falls back to scripted events when the pane exposes no input channel', async () => {
    let injected = ''

    withRunner(async code => {
      injected = code

      return JSON.stringify({ acted: 'clicked', success: true })
    })

    await actOnActivePreview({ kind: 'click', ref: '@e1' })

    // The one-trip shape: the engine both acts and re-reads, no locate handshake.
    expect(injected).toContain('"kind":"click"')
    expect(injected).not.toContain('"kind":"locate"')
  })

  it('routes history verbs to the pane instead of the guest page', async () => {
    const back = vi.fn()
    const runner = vi.fn()

    const tabId = openBrowserTab()
    cleanups.push(registerPreviewNav(tabId, { back, forward: vi.fn(), reload: vi.fn() }))
    cleanups.push(registerPreviewScriptRunner(tabId, runner))

    const result = await actOnActivePreview({ kind: 'back' })

    expect(back).toHaveBeenCalledOnce()
    expect(runner).not.toHaveBeenCalled()
    expect(result.success).toBe(true)
    expect(result.note).toContain('elements')
  })

  it('reports history verbs with no pane to drive', async () => {
    expect((await actOnActivePreview({ kind: 'reload' })).error).toContain('open_preview')
  })

  /** A pane whose document moves the moment the click lands, the way a link or a
   *  form submit does. `doc` is what the real pane publishes off its webview. */
  const withNavigatingPane = ({ nav = true }: { nav?: boolean } = {}) => {
    const tabId = openBrowserTab()
    let generation = 0

    cleanups.push(
      registerPreviewScriptRunner(tabId, async code => {
        if (code.includes('"kind":"locate"')) {
          return JSON.stringify({ acted: 'looking at a "Learn more"', point: { x: 120, y: 80 }, success: true })
        }

        // The read-back runs on the OUTGOING document: same url, every handle
        // still matched. This is exactly the shape measured live.
        return JSON.stringify({
          delta: { same: 115 },
          hit: { onTarget: true, tag: 'A', trusted: true, what: '#more' },
          success: true,
          title: 'Old Page',
          url: 'https://example.com/'
        })
      })
    )
    cleanups.push(
      registerPreviewInput(tabId, {
        focus: vi.fn(),
        send: () => {
          // The click starts a navigation: the pane sees did-start-loading.
          if (nav) {
            generation += 1
          }
        }
      })
    )
    cleanups.push(
      registerPreviewNav(tabId, {
        back: vi.fn(),
        doc: () => ({ generation, url: generation ? 'https://www.iana.org/help/example-domains' : 'https://example.com/' }),
        forward: vi.fn(),
        reload: vi.fn()
      })
    )
  }

  // Measured live before the fix: a search submit that really did land on the
  // results page answered with the home page's url and `delta: {same: 115}`, and
  // a link click that navigated answered `{same: 1}`. Both said success, so the
  // agent concluded its click had done nothing and retried or gave up.
  it('does not pass off the outgoing document as the current page', async () => {
    withNavigatingPane()

    const result = await actOnActivePreview({ kind: 'click', ref: 'lnk-learn-more' })

    expect(result.success).toBe(true)
    // The stale snapshot is dropped rather than handed over: every ref in it
    // belongs to a document being torn down.
    expect(result.delta).toBeUndefined()
    expect(result.elements).toBeUndefined()
    expect(result.note).toContain('navigated')
    // And the url is the document actually being committed.
    expect(result.url).toBe('https://www.iana.org/help/example-domains')
  })

  it('still returns the inventory when the page did not move', async () => {
    withNavigatingPane({ nav: false })

    const result = await actOnActivePreview({ kind: 'click', ref: 'lnk-learn-more' })

    // The delta is the whole point of the cheap path — it must survive a click
    // that genuinely changed nothing but the page's own state.
    expect(result.delta).toEqual({ same: 115 })
    expect(result.note).toBeUndefined()
    expect(result.url).toBe('https://example.com/')
  })

  // A pane too old to publish `doc` must keep working: an unknown answer is not
  // a confirmed navigation, so the snapshot is still the best thing we have.
  it('keeps the snapshot when the pane cannot report its document', async () => {
    const tabId = openBrowserTab()

    cleanups.push(
      registerPreviewScriptRunner(tabId, async code =>
        code.includes('"kind":"locate"')
          ? JSON.stringify({ acted: 'looking at button "Save"', point: { x: 12, y: 8 }, success: true })
          : JSON.stringify({ delta: { same: 3 }, hit: { onTarget: true, tag: 'BUTTON', trusted: true }, success: true })
      )
    )
    cleanups.push(registerPreviewInput(tabId, { focus: vi.fn(), send: vi.fn() }))
    cleanups.push(registerPreviewNav(tabId, { back: vi.fn(), forward: vi.fn(), reload: vi.fn() }))

    expect((await actOnActivePreview({ kind: 'click', ref: '@e1' })).delta).toEqual({ same: 3 })
  })

  // The coordinate bug's signature: real input arrives, but on the wrong node.
  // The old witness only asked "did anything arrive", so a click that missed by
  // a scale factor was indistinguishable from one that hit.
  it('fails when the pointer reaches the page but lands on the wrong element', async () => {
    const tabId = openBrowserTab()

    cleanups.push(
      registerPreviewScriptRunner(tabId, async code =>
        code.includes('"kind":"locate"')
          ? JSON.stringify({ acted: 'looking at a "T2"', point: { x: 620, y: 130 }, success: true })
          : JSON.stringify({
              elements: [],
              hit: { onTarget: false, tag: 'DIV', trusted: true, what: '#pad' },
              success: true
            })
      )
    )
    cleanups.push(registerPreviewInput(tabId, { focus: vi.fn(), send: vi.fn() }))

    const result = await actOnActivePreview({ kind: 'click', ref: 'lnk-t2' })

    expect(result.success).toBe(false)
    expect(result.error).toContain('#pad')
    expect(result.error).toContain('T2')
  })

  // A witness with no verdict (an older engine still parked on a long-lived
  // page) must not be read as a miss — that would fail every healthy click.
  it('treats a witness without a verdict as a hit', async () => {
    const tabId = openBrowserTab()

    cleanups.push(
      registerPreviewScriptRunner(tabId, async code =>
        code.includes('"kind":"locate"')
          ? JSON.stringify({ acted: 'looking at button "Save"', point: { x: 12, y: 8 }, success: true })
          : JSON.stringify({ elements: [], hit: { tag: 'BUTTON', trusted: true }, success: true })
      )
    )
    cleanups.push(registerPreviewInput(tabId, { focus: vi.fn(), send: vi.fn() }))

    expect(await actOnActivePreview({ kind: 'click', ref: '@e1' })).toMatchObject({ success: true })
  })

  it('sends pointer input in device-independent pixels, not the guest’s CSS pixels', async () => {
    const tabId = openBrowserTab()
    const send = vi.fn()

    cleanups.push(
      registerPreviewScriptRunner(tabId, async code =>
        code.includes('"kind":"locate"')
          ? // What getBoundingClientRect reports: CSS pixels inside the page.
            JSON.stringify({ acted: 'looking at a "T2"', point: { x: 620, y: 130 }, success: true })
          : JSON.stringify({ elements: [], hit: { onTarget: true, tag: 'A', trusted: true }, success: true })
      )
    )
    cleanups.push(
      registerPreviewInput(tabId, { focus: vi.fn(), send, zoom: () => 1.2220792770385742 })
    )

    await actOnActivePreview({ kind: 'click', ref: 'lnk-t2' })

    // Unconverted, this went out as (620, 130) and the guest resolved it to
    // (507, 106) — the container, not the link.
    expect(send.mock.calls.map(([event]) => event).find(event => event.type === 'mouseDown')).toMatchObject({
      x: 507,
      y: 106
    })
  })
})
