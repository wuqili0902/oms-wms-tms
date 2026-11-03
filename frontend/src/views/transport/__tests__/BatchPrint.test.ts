/*
 * 批量打单 prints the label, so it is the screen where a waybill number's
 * provenance is worth money: with no KDNIAO_* credentials the server hands back a
 * number it assembled from a prefix + today's date + a hash of the order id, and
 * that number prints exactly like the carrier's.  Nothing on the row used to say so
 * — the operator pasted a label the courier has never seen, and 轨迹查询 has
 * nothing to read for it.
 *
 * The response carries tracking_source / tracking_source_note (see
 * src/logistics/service.py).  These tests pin that the screen shows it, and pin the
 * row alignment: createAllWaybills used to write result i into items[i] while the
 * requests were built from the *filtered* rows, so with a blank row in the middle
 * every waybill number landed on the wrong recipient.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus, { ElMessage } from 'element-plus'
import { createRouter, createMemoryHistory } from 'vue-router'

const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }))

vi.mock('../../../api', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: {} }), post: postMock },
}))

const settle = () => new Promise(r => setTimeout(r, 60))

const CSV_ROWS = [
  'order_id,recipient_name,recipient_phone,recipient_address,carrier_code',
  'ORD-1,张三,13800138000,上海市浦东新区,zto',
  'ORD-2,李四,13900139000,北京市朝阳区,sf',
].join('\n')

/** CSV import gives us rows we can address by index (5 inputs per row, carrier last). */
async function mountWithCsv(csv = CSV_ROWS) {
  const BatchPrint = (await import('../BatchPrint.vue')).default
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/transport/batch-print', name: 'BatchPrint', component: BatchPrint }],
  })
  router.push('/transport/batch-print')
  await router.isReady()
  const wrapper = mount(BatchPrint, {
    global: { plugins: [createPinia(), ElementPlus, router] },
    attachTo: document.body,
  })
  const file = new File([csv], 'orders.csv', { type: 'text/csv' })
  const upload = wrapper.findComponent({ name: 'ElUpload' })
  // on-change is a declared prop of ElUpload, so $emit never reaches it.
  const onChange = (upload.vm as any).$.props.onChange
  onChange({ raw: file, name: 'orders.csv', status: 'ready', uid: '1', size: file.size })
  await settle()
  return wrapper
}

function buttons(wrapper: any): string[] {
  return wrapper.findAllComponents({ name: 'ElButton' }).map((b: any) => b.text())
}

async function clickButton(wrapper: any, label: string) {
  const all = wrapper.findAllComponents({ name: 'ElButton' })
  const btn = all.find((b: any) => b.text().includes(label))
  expect(btn, `button ${label}`).toBeTruthy()
  await btn!.trigger('click')
  await settle()
}

/** Every data row renders 5 inputs: order / name / phone / address / carrier select. */
function rowInput(wrapper: any, rowIndex: number, column: number) {
  return wrapper.findAll('tr')[rowIndex + 1].findAll('input')[column]
}

describe('BatchPrint.vue — 面单号的出处', () => {
  let warnSpy: any

  beforeEach(() => {
    postMock.mockReset()
    warnSpy = vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({} as any))
    vi.spyOn(ElMessage, 'success').mockImplementation(() => ({} as any))
    vi.spyOn(ElMessage, 'error').mockImplementation(() => ({} as any))
  })

  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('labels a locally generated number, and says why', async () => {
    postMock.mockResolvedValue({
      data: {
        tracking_number: 'ZT260101AB12CD34',
        tracking_source: 'local_placeholder',
        tracking_source_note: '未配置快递鸟凭据（KDNIAO_EBUSINESS_ID / KDNIAO_API_KEY）：面单号由本地生成，快递侧没有这张面单',
      },
    })
    const wrapper = await mountWithCsv()
    await clickButton(wrapper, '批量下单')

    expect(wrapper.text()).toContain('本地生成')
    expect(wrapper.find('[data-testid="placeholder-alert"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="placeholder-alert"]').text()).toContain('快递侧没有这张面单')
    expect(warnSpy.mock.calls.some(([m]: any) => String(m).includes('本地生成'))).toBe(true)
  })

  it('a carrier-issued number is not flagged', async () => {
    postMock.mockResolvedValue({
      data: { tracking_number: 'ZT26010100001', tracking_source: 'kdniao', tracking_source_note: '面单号由快递鸟返回' },
    })
    const wrapper = await mountWithCsv()
    await clickButton(wrapper, '批量下单')

    expect(wrapper.find('[data-testid="placeholder-alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('快递鸟')
    expect(wrapper.text()).not.toContain('本地生成')
    expect(warnSpy.mock.calls.some(([m]: any) => String(m).includes('本地生成'))).toBe(false)
  })

  it('a number with no provenance in the response is not claimed as the carrier\'s', async () => {
    // An absent tracking_source must not be rendered as 快递鸟: that would be the
    // screen vouching for a number it has no information about.
    postMock.mockResolvedValue({ data: { tracking_number: 'ZT26010199999' } })
    const wrapper = await mountWithCsv()
    await clickButton(wrapper, '批量下单')

    expect(wrapper.text()).toContain('ZT26010199999')
    expect(wrapper.text()).not.toContain('快递鸟')
    expect(wrapper.text()).not.toContain('本地生成')
  })

  it('writes each waybill number back onto its own row', async () => {
    // Row 1 has no address in this CSV, so it is filtered out of the request list:
    // the two responses belong to rows 2 and 3.
    const csv = [
      'order_id,recipient_name,recipient_phone,recipient_address,carrier_code',
      'ORD-1,张三,13800138000,,zto',
      'ORD-2,李四,13900139000,北京市朝阳区,sf',
      'ORD-3,王五,13700137000,成都市武侯区,sto',
    ].join('\n')
    const responses = [
      { data: { tracking_number: 'ZT-ROW2', tracking_source: 'kdniao' } },
      { data: { tracking_number: 'ZT-ROW3', tracking_source: 'kdniao' } },
    ]
    postMock.mockImplementation(async () => responses.shift())

    const wrapper = await mountWithCsv(csv)
    await clickButton(wrapper, '批量下单')

    const rows = wrapper.findAll('tr').slice(1)
    expect(rows[0].find('input').element.value).toBe('ORD-1')
    expect(rows[0].text()).not.toContain('ZT-ROW2')
    expect(rows[1].find('input').element.value).toBe('ORD-2')
    expect(rows[1].text()).toContain('ZT-ROW2')
    expect(rows[2].find('input').element.value).toBe('ORD-3')
    expect(rows[2].text()).toContain('ZT-ROW3')
    expect(postMock).toHaveBeenCalledTimes(2)
  })

  it('warns before printing a label the carrier never issued', async () => {
    postMock.mockResolvedValue({
      data: { tracking_number: 'ZT260101AB12CD34', tracking_source: 'local_placeholder' },
    })
    const wrapper = await mountWithCsv()
    await clickButton(wrapper, '批量下单')
    warnSpy.mockClear()
    await clickButton(wrapper, '批量打印')

    expect(warnSpy.mock.calls.some(([m]: any) => String(m).includes('本地生成'))).toBe(true)
  })

  it('asks the server for a waybill per valid row, with the row\'s carrier', async () => {
    postMock.mockResolvedValue({ data: { tracking_number: 'ZT26010100002', tracking_source: 'kdniao' } })
    const wrapper = await mountWithCsv()
    await clickButton(wrapper, '批量下单')

    expect(postMock).toHaveBeenCalledTimes(2)
    const bodies = postMock.mock.calls.map((c: any) => c[1])
    expect(bodies[0]).toMatchObject({ order_id: 'ORD-1', carrier_code: 'zto' })
    expect(bodies[1]).toMatchObject({ order_id: 'ORD-2', carrier_code: 'sf' })
    expect(postMock.mock.calls[0][0]).toBe('/logistics/waybill/create')
  })

  it('the table headers name the columns the operator must check', async () => {
    postMock.mockResolvedValue({ data: { tracking_number: 'ZT26010100003', tracking_source: 'kdniao' } })
    const wrapper = await mountWithCsv()
    expect(buttons(wrapper)).toContain('批量下单')
    expect(buttons(wrapper)).toContain('批量打印')
    expect(wrapper.text()).toContain('面单号')
    expect(rowInput(wrapper, 0, 0).element.value).toBe('ORD-1')
  })
})
