/**
 * The carriers the consoles list, in the codes the API stores.
 *
 * ``Shipment.carrier`` is free text on the server, so these screens offer the
 * short list and let an unlisted carrier be typed — and the list lives here
 * because four screens were keeping four copies of it, which is how one screen
 * ended up offering 韵达 and another not offering it.
 */
export const CARRIERS = [
  { value: 'sf_express', label: '顺丰' },
  { value: 'zto', label: '中通' },
  { value: 'yunda', label: '韵达' },
  { value: 'jd_logistics', label: '京东物流' },
  { value: 'ems', label: 'EMS' },
] as const

export const carrierLabel = (code: string): string =>
  CARRIERS.find(c => c.value === code)?.label ?? code
