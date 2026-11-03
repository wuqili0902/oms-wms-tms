import { describe, expect, it } from 'vitest'

import { errText } from '../api/errors'

/**
 * ``errText`` is what every view now toasts.  The point of the order is that the
 * server's sentence — the one written for the operator who pressed 提交 — wins
 * over axios's transport message ("Request failed with status code 422"), which
 * is what a screen reading ``response.data.detail`` showed once the API answered
 * in the documented envelope: the server had explained the refusal and the screen
 * said 保存失败.
 */
describe('errText', () => {
  it('shows the server sentence the api client put on the error', () => {
    const error = Object.assign(new Error('Request failed with status code 422'), {
      userMessage: "hub_type must be one of: primary, secondary, cargo_station, got 'sorting'",
      response: { status: 422, data: { success: false, error: { code: 'VALIDATION_ERROR' } } },
    })
    expect(errText(error, '枢纽创建失败')).toBe(
      "hub_type must be one of: primary, secondary, cargo_station, got 'sorting'",
    )
  })

  it('falls back to the legacy detail when a response has no envelope', () => {
    const error = Object.assign(new Error('Request failed with status code 400'), {
      response: { status: 400, data: { detail: '订单不存在' } },
    })
    expect(errText(error, '加载失败')).toBe('订单不存在')
  })

  it('prefers the envelope over a legacy detail on the same response', () => {
    const error = Object.assign(new Error('Request failed'), {
      userMessage: 'count is required — the observation is the order count',
      response: { status: 422, data: { detail: '旧字段' } },
    })
    expect(errText(error)).toBe('count is required — the observation is the order count')
  })

  it('uses the transport message when the server said nothing', () => {
    const error = Object.assign(new Error('Network Timeout'), { response: undefined })
    expect(errText(error, '提交失败')).toBe('Network Timeout')
  })

  it('shows the screen’s own text when there is nothing to report at all', () => {
    expect(errText(undefined, '库存调整失败')).toBe('库存调整失败')
    expect(errText({})).toBe('操作失败')
  })
})
