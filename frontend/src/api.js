// Thin client for the extraction API. Job status is one of:
// "pending" | "processing" | "completed" | "failed".

export async function submitPdf(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/v1/extractions', { method: 'POST', body: form })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} — ${body.detail ?? 'upload rejected'}`)
  }
  return body // { job_id, status }
}

export async function getJob(id) {
  const res = await fetch(`/v1/extractions/${id}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() // { job_id, status, result, error, created_at, updated_at }
}
