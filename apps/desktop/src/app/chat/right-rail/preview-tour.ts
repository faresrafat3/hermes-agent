/**
 * PREVIEW TOUR — runs tour actions inside the preview pane's guest page, so a
 * tour can walk through ANY web app open in the in-app browser, not just
 * Hermes itself.
 *
 * The guest page is out-of-process; nothing here can touch its DOM directly.
 * Instead the first action injects a self-contained bundle over
 * `executeJavaScript` — the vendored driver.js IIFE, its stylesheet, and the
 * same engine/collector SOURCE the app surface runs (see lib/tour/engine.ts's
 * self-containment contract) — parked on window globals so subsequent actions
 * reuse the live driver instance. Injection is idempotent and vanishes with
 * the page (a navigation resets the tour, which is the right behavior).
 *
 * Dynamic-imported by run-tour.ts so the raw driver.js payload stays out of
 * the boot path.
 */

import driverCss from 'driver.js/dist/driver.css?raw'
import driverIife from 'driver.js/dist/driver.js.iife.js?raw'

import { collectTourTargets } from '@/lib/tour/collect-targets'
import { runTourEngine, type TourAction, type TourResult } from '@/lib/tour/engine'

import { activePreviewScriptRunner } from './preview-script-runner'

/** Build the idempotent inject-and-run script for one tour action. */
function buildTourScript(action: TourAction): string {
  return `(function () {
  var w = window;
  if (!w.__hermesTourEngine) {
    ${driverIife}
    w.__hermesTourHolder = {};
    w.__hermesTourCollect = (${collectTourTargets.toString()});
    w.__hermesTourEngine = (${runTourEngine.toString()});
  }
  if (!document.getElementById('__hermes-tour-style')) {
    var style = document.createElement('style');
    style.id = '__hermes-tour-style';
    style.textContent = ${JSON.stringify(driverCss)};
    (document.head || document.documentElement).appendChild(style);
  }
  return JSON.stringify(w.__hermesTourEngine(
    w.driver.js.driver,
    w.__hermesTourHolder,
    ${JSON.stringify(action)},
    w.__hermesTourCollect,
    document
  ));
})()`
}

/** Cap on one round trip into the guest page.
 *
 *  A tour action can start a navigation — `next` onto a step whose highlight is
 *  a link the page then follows, or a guest that redirects mid-walk — and that
 *  tears the document down while the injected script is still in flight. The
 *  promise `executeJavaScript` returned then never settles: not resolved, not
 *  rejected, so the surrounding try/catch never fires either. Without this the
 *  tool sits on it for the bridge's full 45s deadline (`_TOUR_TIMEOUT_S`) and
 *  the turn stalls on what was usually a successful step.
 *
 *  Same reasoning and roughly the same budget as the act engine's
 *  ACT_TIMEOUT_MS; a tour step is allowed a little longer because driver.js
 *  animates its stage into place before answering. */
const TOUR_TIMEOUT_MS = 10_000

/** Run one tour action in the ACTIVE preview tab's page. */
export async function runPreviewTour(action: TourAction): Promise<TourResult> {
  const run = activePreviewScriptRunner()

  if (!run) {
    return { error: 'No live page is open in the preview pane — open one first.', success: false }
  }

  // A rejection is folded in rather than thrown so the timeout below is the only
  // way out that is not an answer: the caller distinguishes "the page refused"
  // from "the page went quiet", and both beat an unsettled promise.
  const raw = await Promise.race([
    run(buildTourScript(action)).catch((error: unknown) => new Error(String(error))),
    new Promise<undefined>(resolve => setTimeout(resolve, TOUR_TIMEOUT_MS))
  ])

  if (raw === undefined) {
    // Reported as a success: the action was delivered and most likely ran, and
    // the page going quiet mid-tour is a navigation, not a failed step.
    return {
      hint: 'The page stopped answering — it is probably navigating, which resets the tour. Call targets to see where you landed.',
      success: true
    }
  }

  if (raw instanceof Error) {
    return { error: 'The page rejected the tour action: ' + raw.message, success: false }
  }

  if (typeof raw !== 'string' || !raw) {
    return { error: 'The page did not answer the tour action.', success: false }
  }

  return JSON.parse(raw) as TourResult
}
