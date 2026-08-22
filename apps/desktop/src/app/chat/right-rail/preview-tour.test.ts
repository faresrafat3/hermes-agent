import { beforeEach, describe, expect, it, vi } from 'vitest'

import { $rightRailActiveTabId } from '@/store/layout'
import { closeRightRail, openPreview, type PreviewTarget } from '@/store/preview'

import { registerPreviewScriptRunner } from './preview-script-runner'
import { runPreviewTour } from './preview-tour'

function urlTarget(url: string): PreviewTarget {
  return { kind: 'url', label: 'Browser', source: url, url }
}

/**
 * A tour action can start a navigation — `next` onto a step whose highlight is a
 * link the page follows, or a guest that redirects mid-walk — and that tears the
 * document down while the injected script is still in flight. The promise
 * `executeJavaScript` returned then never settles, so `runTour`'s try/catch never
 * fires either, and the tool sat on it for the bridge's full 45s tour deadline.
 *
 * This module had no tests at all, which is how an unbounded await survived in
 * it while the neighbouring act engine grew an explicit cap for the same reason.
 */
describe('runPreviewTour', () => {
  let cleanups: Array<() => void> = []

  const openBrowserTab = () => {
    openPreview(urlTarget('https://example.com'), 'tool-result')

    return $rightRailActiveTabId.get()!
  }

  beforeEach(() => {
    vi.useRealTimers()

    for (const cleanup of cleanups) {
      cleanup()
    }

    cleanups = []
    closeRightRail()
    window.localStorage.clear()
  })

  it('tells the agent to open a page when no pane is behind the tab', async () => {
    const result = await runPreviewTour({ kind: 'targets' })

    expect(result.success).toBe(false)
    expect(result.error).toContain('open one first')
  })

  it('returns the page’s answer for a normal action', async () => {
    let injected = ''

    cleanups.push(
      registerPreviewScriptRunner(openBrowserTab(), async code => {
        injected = code

        return JSON.stringify({ action: 'show', activeStep: 0, success: true })
      })
    )

    const result = await runPreviewTour({ kind: 'show', selector: '#save', title: 'Save' })

    expect(result).toMatchObject({ action: 'show', success: true })
    // Self-contained bundle: driver.js and the engine travel with the action.
    expect(injected).toContain('__hermesTourEngine')
    expect(injected).toContain('"selector":"#save"')
  })

  it('gives up on a page that never answers instead of eating the bridge deadline', async () => {
    // A document torn down mid-navigation leaves the injected promise unsettled
    // forever: not resolved, not rejected.
    cleanups.push(registerPreviewScriptRunner(openBrowserTab(), () => new Promise<never>(() => undefined)))

    const started = Date.now()
    const result = await runPreviewTour({ kind: 'next' })
    const waited = Date.now() - started

    // Reported as a success — the action was delivered and a quiet page mid-tour
    // is a navigation, not a failed step.
    expect(result.success).toBe(true)
    expect(result.hint).toContain('navigating')
    // The point of the cap: well under the gateway's 45s tour timeout. Loose
    // bound so a busy runner cannot flake it.
    expect(waited).toBeLessThan(30_000)
  }, 40_000)

  it('reports a page that rejects the action rather than throwing', async () => {
    cleanups.push(
      registerPreviewScriptRunner(openBrowserTab(), async () => {
        throw new Error('Script failed to execute')
      })
    )

    const result = await runPreviewTour({ kind: 'targets' })

    expect(result.success).toBe(false)
    expect(result.error).toContain('Script failed to execute')
  })

  it('reports a page that answers with nothing', async () => {
    cleanups.push(registerPreviewScriptRunner(openBrowserTab(), async () => ''))

    expect((await runPreviewTour({ kind: 'targets' })).error).toContain('did not answer')
  })
})
