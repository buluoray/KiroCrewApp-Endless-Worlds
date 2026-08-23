/** Which failed requests are a signal about the APP, and which are the host's noise.
 *
 *  Kept in its own module, pure and tested, because it decides whether the gate goes
 *  red: a rule too loose hides the defect it exists to catch, and one too tight fails a
 *  run for something the app did not do.
 */

/** The app's own API prefix. Its calls are reported in full and policed strictly. */
export const APP_API = /\/api\/apps\/[^/]+\//

/** Requests the dashboard itself makes that cannot succeed on a headless, non-desktop
 *  instance. An ignore list, not a blanket filter: anything else that fails stays
 *  visible, since that is how a blank frame explains itself. */
export const IGNORED_FAILURES = [/\/api\/instances\b/]

/** True when a failed request says nothing about the app and must not fail the run.
 *
 *  Two classes:
 *
 *  1. The host endpoints above, which are expected to fail here.
 *  2. An ABORTED request that is not the app's own. The dashboard fires its boot calls
 *     (agents, theme, approvals, its project icon) while the driver is still navigating
 *     to the app, and the browser cancels whatever is in flight when it navigates — so
 *     the abort is a race against the host's cold start, not a defect. It is also
 *     nondeterministic: the same commit passed one run and failed the next on nothing
 *     but runner speed, which is the kind of red that teaches people to hit rerun.
 *
 *  An abort of the APP's own request is NOT noise and stays a failure. That is the
 *  narrow half that matters: a scene frame whose second document request was cancelled
 *  is exactly the defect class this harness was built to catch, and a blanket
 *  ignore-all-aborts rule would have let it through silently.
 */
export function isNoiseFailure(url, errorText = '') {
  if (IGNORED_FAILURES.some((re) => re.test(url))) return true
  return errorText.includes('ERR_ABORTED') && !APP_API.test(url)
}
