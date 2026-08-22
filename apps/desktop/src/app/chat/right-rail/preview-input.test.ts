import { describe, expect, it } from 'vitest'

import { toInputPoint } from './preview-input'

/**
 * The act engine measures targets with `getBoundingClientRect`, i.e. CSS pixels
 * inside the zoomed guest page. `sendInputEvent` coordinates are scaled by the
 * page's zoom on the way in. Measured live against a probe page that reports
 * where its own `pointerdown` landed:
 *
 *     css_received = dip_sent / zoomFactor
 *
 * At Fares's zoom factor of 1.2220792770385742 the code was sending the measured
 * CSS point straight through, so a click aimed at a link centred at CSS
 * (620, 130) arrived at CSS (507, 106) — the page container, not the link — and
 * was still reported as a successful click, because the read-back rides the
 * separate script channel and saw a perfectly healthy page.
 */
const ZOOM = 1.2220792770385742

describe('toInputPoint', () => {
  it('is the identity at 100%, which is why the bug hid for so long', () => {
    expect(toInputPoint({ x: 620, y: 130 }, 1)).toEqual({ x: 620, y: 130 })
  })

  it('lands the pointer on the CSS point that was aimed at', () => {
    // The property that actually matters, stated as the inverse of the measured
    // law: whatever we send, the page must resolve it to the aimed coordinate.
    for (const factor of [0.5, 0.75, 0.9, 1, ZOOM, 1.5, 2, 3]) {
      for (const aimed of [
        { x: 620, y: 130 },
        { x: 320, y: 410 },
        { x: 1, y: 1 }
      ]) {
        const sent = toInputPoint(aimed, factor)

        // css_received = dip_sent / factor, and rounding to whole pixels is the
        // only error allowed.
        expect(Math.abs(sent.x / factor - aimed.x)).toBeLessThanOrEqual(0.5 / factor + 1e-9)
        expect(Math.abs(sent.y / factor - aimed.y)).toBeLessThanOrEqual(0.5 / factor + 1e-9)
      }
    }
  })

  it('scales up by the zoom factor — the live-measured numbers', () => {
    // Regression pin against the real factor read off the running app. Sending
    // the raw CSS point (the old behaviour) put the click at (507, 106).
    expect(toInputPoint({ x: 620, y: 130 }, ZOOM)).toEqual({ x: 758, y: 159 })
    expect(toInputPoint({ x: 320, y: 410 }, ZOOM)).toEqual({ x: 391, y: 501 })
  })

  it('treats a nonsense factor as unzoomed rather than poisoning the point', () => {
    // Sending NaN would put the click at an unpredictable spot; not scaling is
    // the safer failure, and matches the pre-zoom behaviour.
    for (const factor of [0, -2, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(toInputPoint({ x: 620, y: 130 }, factor)).toEqual({ x: 620, y: 130 })
    }
  })

  it('returns whole pixels, since the input channel takes integers', () => {
    const point = toInputPoint({ x: 621, y: 131 }, ZOOM)

    expect(Number.isInteger(point.x)).toBe(true)
    expect(Number.isInteger(point.y)).toBe(true)
  })
})
