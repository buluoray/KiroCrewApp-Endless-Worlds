import assert from 'node:assert/strict'
import { test } from 'node:test'

import { isNoiseFailure } from './failures.mjs'

const APP = 'http://localhost:9/api/apps/endless-worlds/runs/abc/chronicle'
const HOST = 'http://localhost:9/api/agents'

test('an aborted host request is noise: it is a race against the dashboard boot', () => {
  assert.equal(isNoiseFailure(HOST, 'net::ERR_ABORTED'), true)
  assert.equal(isNoiseFailure('http://localhost:9/api/config/theme', 'net::ERR_ABORTED'), true)
  assert.equal(isNoiseFailure('http://localhost:9/app-assets/projects/icon.svg', 'net::ERR_ABORTED'), true)
})

test('an aborted APP request is NOT noise — that is the defect class this gate exists for', () => {
  assert.equal(isNoiseFailure(APP, 'net::ERR_ABORTED'), false)
})

test('a host request that failed for any other reason stays visible', () => {
  // Only ABORT is a boot race. A refused or reset host request means the instance is
  // broken, and a run against a broken instance must not report success.
  assert.equal(isNoiseFailure(HOST, 'net::ERR_CONNECTION_REFUSED'), false)
  assert.equal(isNoiseFailure(HOST, ''), false)
})

test('the declared host ignore list still applies whatever the error', () => {
  assert.equal(isNoiseFailure('http://localhost:9/api/instances', 'net::ERR_FAILED'), true)
})
