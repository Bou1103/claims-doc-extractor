import { useCallback, useEffect, useRef, useState } from 'react'
import { getJob, submitPdf } from './api'

const TERMINAL = new Set(['completed', 'failed'])

export default function App() {
  const [file, setFile] = useState(null)
  const [job, setJob] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef(undefined)

  const stopPolling = useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = undefined
  }, [])

  useEffect(() => stopPolling, [stopPolling])

  const poll = useCallback((id) => {
    const tick = async () => {
      try {
        const next = await getJob(id)
        setJob(next)
        if (TERMINAL.has(next.status)) {
          setBusy(false)
          if (next.status === 'failed') setError(next.error ?? 'extraction failed')
          return
        }
      } catch (e) {
        setBusy(false)
        setError(String(e))
        return
      }
      timer.current = window.setTimeout(tick, 1500)
    }
    void tick()
  }, [])

  const onSubmit = async () => {
    if (!file) return
    stopPolling()
    setError(null)
    setJob(null)
    setBusy(true)
    try {
      const created = await submitPdf(file)
      setJob({ job_id: created.job_id, status: created.status, result: null, error: null })
      poll(created.job_id)
    } catch (e) {
      setBusy(false)
      setError(String(e))
    }
  }

  return (
    <main>
      <h1>Claims Document Extraction</h1>
      <p className="sub">Test console — upload a PDF invoice and watch it process.</p>

      <div className="uploader">
        <input
          type="file"
          accept="application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button onClick={onSubmit} disabled={!file || busy}>
          {busy ? 'Working…' : 'Extract'}
        </button>
      </div>

      {job && (
        <section className="panel">
          <div className="row">
            <span className="key">Job</span>
            <code>{job.job_id}</code>
          </div>
          <div className="row">
            <span className="key">Status</span>
            <span className={`badge ${job.status}`}>{job.status}</span>
          </div>
        </section>
      )}

      {error && (
        <section className="panel error">
          <h2>Error</h2>
          <pre>{error}</pre>
        </section>
      )}

      {job?.result && <Result data={job.result} />}
    </main>
  )
}

function Result({ data }) {
  return (
    <section className="panel">
      <h2>Header</h2>
      <table>
        <tbody>
          {Object.entries(data.header).map(([k, v]) => (
            <tr key={k}>
              <th>{k}</th>
              <td>{v ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Line items</h2>
      <table>
        <thead>
          <tr>
            <th>Description</th>
            <th>Qty</th>
            <th>Unit price</th>
            <th>Amount</th>
          </tr>
        </thead>
        <tbody>
          {data.line_items.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">none</td>
            </tr>
          )}
          {data.line_items.map((li, i) => (
            <tr key={i}>
              <td>{li.description}</td>
              <td>{li.quantity ?? '—'}</td>
              <td>{li.unit_price ?? '—'}</td>
              <td>{li.amount ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Warnings</h2>
      {data.warnings.length === 0 ? (
        <p className="muted">none</p>
      ) : (
        <ul>
          {data.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      <details>
        <summary>Raw JSON</summary>
        <pre>{JSON.stringify(data, null, 2)}</pre>
      </details>
    </section>
  )
}
