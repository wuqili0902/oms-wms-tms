import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
}))

vi.mock('element-plus', () => ({ ElMessage: { error: mocks.error, success: mocks.success } }))
vi.mock('../api', () => ({ default: { get: mocks.get } }))

describe('useExport', () => {
  let downloadCSV: (url: string, filename: string) => Promise<void>
  let createObjectURL: any
  let revokeObjectURL: any
  let linkClick: any

  beforeEach(async () => {
    mocks.get.mockReset()
    mocks.error.mockReset()
    mocks.success.mockReset()

    linkClick = vi.fn()
    createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock' as any)
    revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(document, 'createElement').mockReturnValue({ href: '', download: '', click: linkClick } as any)

    const { useExport } = await import('../composables/useExport')
    downloadCSV = useExport().downloadCSV
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('downloads CSV blob and revokes URL', async () => {
    mocks.get.mockResolvedValueOnce({ data: 'a,b,c\n1,2,3' })
    await downloadCSV('/export/orders', 'orders.csv')

    expect(mocks.get).toHaveBeenCalledWith('/export/orders', { responseType: 'blob' })
    expect(createObjectURL).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock')
    expect(mocks.success).toHaveBeenCalledWith('导出成功')
    expect(linkClick).toHaveBeenCalledTimes(1)
  })

  it('shows error on failure', async () => {
    mocks.get.mockRejectedValueOnce(new Error('network'))
    await downloadCSV('/export/x', 'x.csv')

    expect(mocks.error).toHaveBeenCalledWith('导出失败')
    expect(mocks.success).not.toHaveBeenCalled()
  })
})
