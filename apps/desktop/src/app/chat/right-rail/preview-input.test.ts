import { describe, expect, it } from 'vitest'

import { toDeviceIndependent } from './preview-input'

/**
 * The act engine measures targets with `getBoundingClientRect`, i.e. CSS pixels
 * inside the zoomed guest page. `sendInputEvent` is a browser-level input
 * channel and takes device-independent pixels. Converting between them is not
 * cosmetic: at Fares's measured zoom factor of 1.2220792770385742, a click aimed
 * at the centre of a link at (620, 130) arrived at (507, 106) and activated the
 * page container instead — reported as a successful click, because the read-back
 * rides the separate script channel and saw a perfectly healthy page.
 */
describe('toDeviceIndependent', () => {
  it('is the identity at 100%, which is why the bug hid for so long', () => {
    expect(toDeviceIndependent({ x: 620, y: 130 }, 1)).toEqual({ x: 620, y: 130 })
  })

  it('divides by the zoom factor — the live-measured miss', () => {
    // Regression pin: the factor and both coordinates are the real numbers read
    // off the running app. Before the fix the point went out unconverted, so the
    // guest received (620, 130) as DIP and resolved it to (507, 106) CSS.
    const factor = 1.2220792770385742

    expect(toDeviceIndependent({ x: 620, y: 130 }, factor)).toEqual({ x: 507, y: 106 })
    expect(toDeviceIndependent({ x: 320, y: 410 }, factor)).toEqual({ x: 262, y: 335 })
  })

  it('round-trips a measured point back to where it was aimed', () => {
    // What actually matters: after conversion, the guest resolves the input to
    // the coordinate the engine measured. Anything else is a mis-aimed click.
    for (const factor of [0.5, 0.9, 1, 1.2220792770385742, 1.5, 2, 3]) {
      const aimed = { x: 620, y: 130 }
      const wire = toDeviceIndependent(aimed, factor)

      expect(Math.abs(wire.x * factor - aimed.x)).toBeLessThanOrEqual(factor / 2 + 1e-9)
      expect(Math.abs(wire.y * factor - aimed.y)).toBeLessThanOrEqual(factor / 2 + 1e-9)
    }
  })

  it('treats a nonsense factor as unzoomed rather than poisoning the point', () => {
    // Dropping or NaN-ing the coordinate would be a worse failure than not
    // scaling it: the click would land at (NaN, NaN) or at the origin.
    for (const factor of [0, -2, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(toDeviceIndependent({ x: 620, y: 130 }, factor)).toEqual({ x: 620, y: 130 })
    }
  })

  it('returns whole pixels, since the input channel takes integers', () => {
    const point = toDeviceIndependent({ x: 621, y: 131 }, 1.2220792770385742)

    expect(Number.isInteger(point.x)).toBe(true)
    expect(Number.isInteger(point.y)).toBe(true)
  })
})
