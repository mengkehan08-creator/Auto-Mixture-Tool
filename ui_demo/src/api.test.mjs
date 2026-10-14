import { test } from 'node:test'
import assert from 'node:assert/strict'
import { apiUrl } from './api.js'

for (const [pathname, expected] of [
  ['/ui', '/api/v1/workflows'],
  ['/ui/', '/api/v1/workflows'],
  ['/notebook-id/proxy/8080/ui', '/notebook-id/proxy/8080/api/v1/workflows'],
  ['/notebook-id/proxy/8080/ui/', '/notebook-id/proxy/8080/api/v1/workflows'],
]) {
  test(`API requests preserve proxy prefix: ${pathname}`, () => {
    assert.equal(apiUrl('workflows', { pathname }), expected)
  })
}
