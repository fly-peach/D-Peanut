/** Minimal LCS line diff for the approval panel (N4): shows +N/-M and per-line marks. */

export interface DiffRow { kind: 'same' | 'add' | 'del'; text: string }

export function diffLines(oldSrc: string, newSrc: string, maxRows = 120): DiffRow[] {
  const a = oldSrc.split('\n')
  const b = newSrc.split('\n')
  const n = a.length
  const m = b.length
  // guard pathological sizes: fall back to naive replace-block when huge
  if (n * m > 400_000) {
    const rows: DiffRow[] = a.map((t): DiffRow => ({ kind: 'del', text: t }))
    for (const t of b) rows.push({ kind: 'add', text: t })
    return rows.slice(0, maxRows)
  }
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const rows: DiffRow[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) { rows.push({ kind: 'same', text: a[i] }); i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { rows.push({ kind: 'del', text: a[i] }); i++ }
    else { rows.push({ kind: 'add', text: b[j] }); j++ }
  }
  while (i < n) rows.push({ kind: 'del', text: a[i++] })
  while (j < m) rows.push({ kind: 'add', text: b[j++] })
  const added = rows.filter((r) => r.kind === 'add').length
  const removed = rows.filter((r) => r.kind === 'del').length
  if (rows.length <= maxRows) return rows
  // keep context around changes when truncating
  const keep = new Set<number>()
  rows.forEach((r, idx) => {
    if (r.kind !== 'same') for (let k = Math.max(0, idx - 2); k <= Math.min(rows.length - 1, idx + 2); k++) keep.add(k)
  })
  const out = rows.filter((_, idx) => keep.has(idx)).slice(0, maxRows)
  out.unshift({ kind: 'same', text: `（截断：+${added} −${removed}）` })
  return out
}

export function diffStats(rows: DiffRow[]): { added: number; removed: number } {
  return {
    added: rows.filter((r) => r.kind === 'add').length,
    removed: rows.filter((r) => r.kind === 'del').length,
  }
}
