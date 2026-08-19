import { useRef, useState } from 'react'

async function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  let data
  try {
    data = await res.json()
  } catch {
    throw new Error(`Request failed (${res.status})`)
  }
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`)
  }
  return data
}

// API base URL. In dev this is empty (Vite proxies /api to localhost:8000).
// In production set VITE_API_BASE_URL to the deployed backend origin.
const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp']

const PRIORITIES = ['', 'high', 'medium', 'low']

function blankTask() {
  return { title: '', owner: '', due: '', priority: '', context: '' }
}

function buildMarkdown(plan) {
  const rows = plan.tasks
    .map(
      (t, i) =>
        `${i + 1}. **${t.title || t.text || '(untitled)'}**` +
        (t.owner ? ` — Owner: ${t.owner}` : '') +
        (t.due ? ` — Due: ${t.due}` : '') +
        (t.priority ? ` — Priority: ${t.priority}` : '') +
        (t.context ? `\n   Context: ${t.context}` : '')
    )
    .join('\n')

  let md = `# Action Plan\n\n`
  if (plan.summary) {
    md += `## Summary\n${plan.summary}\n\n`
  }
  if (plan.tasks.length) {
    md += `## Tasks\n${rows}\n`
  } else {
    md += `## Tasks\nNo action items were found.\n`
  }
  if (plan.open_questions && plan.open_questions.length) {
    md += `\n## Open Questions\n${plan.open_questions
      .map((q, i) => `${i + 1}. ${q}`)
      .join('\n')}\n`
  }
  return md
}

function App() {
  const [preview, setPreview] = useState(null)
  const [rawText, setRawText] = useState('')
  const [notes, setNotes] = useState([])
  const [stage, setStage] = useState('idle') // idle | clean | extract
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [extracted, setExtracted] = useState(null)
  const [failedStep, setFailedStep] = useState(null) // 'ocr' | 'clean' | 'research' | 'synthesize'
  const [plan, setPlan] = useState(null)
  const [toast, setToast] = useState(null)
  const [trace, setTrace] = useState([])
  const reviewRef = useRef(null)

  const scrollTop = () => window.scrollTo({ top: 0, behavior: 'smooth' })
  const scrollToReview = () =>
    reviewRef.current && reviewRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })

  const handleFile = async (file) => {
    if (!file) return
    setError(null)
    setNotes([])
    setExtracted(null)
    setPlan(null)
    setFailedStep(null)
    setTrace([])

    if (!IMAGE_TYPES.includes(file.type)) {
      setError('Please upload an image file (PNG, JPEG, WebP, GIF, or BMP).')
      return
    }

    setPreview(URL.createObjectURL(file))
    await runOcr(file)
  }

  const runOcr = async (file) => {
    const base64 = await fileToBase64(file)
    setLoading(true)
    setError(null)
    setFailedStep(null)
    addTrace('Reading whiteboard photo...')
    try {
      const ocr = await postJSON(`${API_BASE}/api/ocr`, { image: base64 })
      if (!ocr.raw_text || !ocr.raw_text.trim()) {
        setError('OCR returned no text. The photo may be blank or unreadable.')
        return
      }
      setRawText(ocr.raw_text)
      addTrace(`Found ${ocr.lines ? ocr.lines.length : 0} lines of text`)
      await runCleanNotes(ocr.raw_text)
    } catch (err) {
      setFailedStep('ocr')
      setError(`OCR failed: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  const runCleanNotes = async (rawText) => {
    setStage('clean')
    setFailedStep(null)
    addTrace('Cleaning up notes...')
    try {
      const res = await postJSON(`${API_BASE}/api/clean-notes`, { raw_text: rawText })
      setNotes(res.notes)
      addTrace(`Reduced to ${res.notes.length} distinct notes`)
    } catch (err) {
      setFailedStep('clean')
      setError(`Notes cleanup failed: ${err.message}`)
    }
  }

  const updateNote = (i, value) => {
    setNotes((prev) => prev.map((n, idx) => (idx === i ? value : n)))
  }

  const addNote = () => setNotes((prev) => [...prev, ''])
  const removeNote = (i) => setNotes((prev) => prev.filter((_, idx) => idx !== i))

  const runExtract = async () => {
    setError(null)
    setExtracted(null)
    setPlan(null)
    setFailedStep(null)
    setLoading(true)
    scrollTop()
    addTrace('Extracting action items...')
    try {
      const res = await postJSON(`${API_BASE}/api/extract-items`, {
        notes: notes.filter((n) => n.trim()),
      })
      setExtracted(res)
      setStage('extract')
      const itemCount = (res.items || []).length
      addTrace(`Found ${itemCount} action item${itemCount === 1 ? '' : 's'}`)
      const unclear = res.unclear_terms || []
      if (unclear.length) {
        addTrace(`Flagged ${unclear.length} unclear term${unclear.length === 1 ? '' : 's'}: ${unclear.join(', ')}`)
      }
      await runResearchAndSynthesize(res)
    } catch (err) {
      setFailedStep('extract')
      setError(`Extraction failed: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  const runResearchAndSynthesize = async (extractedData) => {
    let researchContext = {}
    const unclear = extractedData.unclear_terms || []
    const hasItems = (extractedData.items || []).length > 0
    if (unclear.length && hasItems) {
      unclear.forEach((term) => addTrace(`Researching: ${term}...`))
      try {
        researchContext = await postJSON(`${API_BASE}/api/research-terms`, {
          terms: unclear,
        })
        unclear.forEach((term) => {
          const res = researchContext[term]
          const found = res && res.summary && res.summary !== 'No reliable information found'
          addTrace(found ? `Researched ${term}: found info` : `No reliable information found for ${term}`)
        })
      } catch (err) {
        setFailedStep('research')
        setError(`Research failed: ${err.message}`)
        return
      }
    } else if (unclear.length && !hasItems) {
      addTrace('No action items — skipping research for non-task content')
    } else {
      addTrace('No unclear terms — skipping research')
    }
    addTrace('Synthesizing plan...')
    try {
      const planRes = await postJSON(`${API_BASE}/api/synthesize-plan`, {
        items: extractedData.items,
        research_context: researchContext,
      })
      // Normalize into editable shape.
      setPlan({
        ...planRes,
        tasks: (planRes.tasks || []).map((t) => ({
          title: t.title || t.text || '',
          owner: t.owner || '',
          due: t.due || '',
          priority: t.priority || '',
          context: t.context || '',
        })),
        open_questions: planRes.open_questions || [],
        summary: planRes.summary || '',
      })
      const taskCount = (planRes.tasks || []).length
      const qCount = (planRes.open_questions || []).length
      addTrace(`Generated ${taskCount} task${taskCount === 1 ? '' : 's'}, ${qCount} open question${qCount === 1 ? '' : 's'}`)
      setTimeout(scrollToReview, 150)
    } catch (err) {
      setFailedStep('synthesize')
      setError(`Synthesis failed: ${err.message}`)
    }
  }

  const retryFailedStep = async () => {
    setError(null)
    if (failedStep === 'ocr' && rawText) {
      await runCleanNotes(rawText)
    } else if (failedStep === 'clean' && rawText) {
      await runCleanNotes(rawText)
    } else if (failedStep === 'research' || failedStep === 'synthesize') {
      await runResearchAndSynthesize(extracted)
    } else if (failedStep === 'ocr') {
      setError('Please re-upload the photo to retry OCR.')
    }
  }

  // --- Editable plan handlers ---
  const updateTask = (i, field, value) => {
    setPlan((prev) => ({
      ...prev,
      tasks: prev.tasks.map((t, idx) => (idx === i ? { ...t, [field]: value } : t)),
    }))
  }
  const addTask = () =>
    setPlan((prev) => ({ ...prev, tasks: [...prev.tasks, blankTask()] }))
  const removeTask = (i) =>
    setPlan((prev) => ({ ...prev, tasks: prev.tasks.filter((_, idx) => idx !== i) }))

  const updateQuestion = (i, value) => {
    setPlan((prev) => ({
      ...prev,
      open_questions: prev.open_questions.map((q, idx) => (idx === i ? value : q)),
    }))
  }
  const addQuestion = () =>
    setPlan((prev) => ({ ...prev, open_questions: [...prev.open_questions, ''] }))
  const removeQuestion = (i) =>
    setPlan((prev) => ({
      ...prev,
      open_questions: prev.open_questions.filter((_, idx) => idx !== i),
    }))

  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }

  const addTrace = (msg) => setTrace((prev) => [...prev, msg])

  const copyMarkdown = async () => {
    const md = buildMarkdown(plan)
    try {
      await navigator.clipboard.writeText(md)
      setError(null)
      showToast('Copied to clipboard')
    } catch (err) {
      setError(`Copy failed: ${err.message}`)
    }
  }

  const downloadMarkdown = () => {
    const md = buildMarkdown(plan)
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'action-plan.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  const steps = [
    { id: 'idle', label: 'Upload' },
    { id: 'clean', label: 'Clean' },
    { id: 'extract', label: 'Extract' },
    { id: 'review', label: 'Review' },
  ]
  const stepIndex = steps.findIndex((s) => s.id === stage)
  const priorityClass = (p) => (p ? `priority-badge priority-${p}` : '')

  return (
    <div className="app">
      <header className="app-header">
        <h1>Whiteboard to Action Plan Agent</h1>
        <p>Turn a whiteboard photo into an editable action plan in seconds.</p>
      </header>

      <div className="stepper">
        {steps.map((s, i) => (
          <div
            key={s.id}
            className={`step ${i === stepIndex ? 'active' : ''} ${i < stepIndex ? 'done' : ''}`}
          >
            <span className="dot">{i + 1}</span>
            {s.label}
          </div>
        ))}
      </div>

      <details className="trace-panel" open={trace.length > 0}>
        <summary>Pipeline trace</summary>
        <ol className="trace-list">
          {trace.map((t, i) => (
            <li key={i}>{t}</li>
          ))}
        </ol>
      </details>

      {error && <div className="banner-error">{error}</div>}

      {loading && (
        <div className="banner-info">
          <span className="spinner" /> Processing…
        </div>
      )}

      {failedStep && failedStep !== 'ocr' && (
        <div className="card">
          <div className="btn-row">
            <button className="btn btn-secondary" onClick={retryFailedStep}>
              Retry {failedStep} step (no re-upload)
            </button>
          </div>
        </div>
      )}

      {stage === 'idle' && (
        <div className="card">
          <label className="upload-zone">
            <strong>Click to choose a whiteboard photo</strong>
            <span className="hint">PNG, JPEG, WebP, GIF, or BMP</span>
            <input type="file" accept="image/*" onChange={(e) => handleFile(e.target.files?.[0])} />
          </label>
          {preview && <img className="preview" src={preview} alt="Selected" />}
        </div>
      )}

      {stage === 'clean' && (
        <div className="card">
          <h2>Cleaned notes (editable)</h2>
          <p className="muted">Fix any OCR mistakes here before continuing.</p>
          {notes.length === 0 && <p className="empty-state">No notes extracted.</p>}
          {notes.map((note, i) => (
            <div className="note-item" key={i}>
              <textarea value={note} onChange={(e) => updateNote(i, e.target.value)} rows={2} />
              <button className="btn btn-danger" onClick={() => removeNote(i)}>
                Remove
              </button>
            </div>
          ))}
          <div className="btn-row">
            <button className="btn btn-secondary" onClick={addNote}>Add note</button>
            <button className="btn btn-primary" onClick={runExtract}>
              Continue → Extract items
            </button>
          </div>
        </div>
      )}

      {stage === 'extract' && plan && (
        <div className="card" ref={reviewRef}>
          <h2>Review &amp; export</h2>

          <div className="field">
            <label>Summary (editable)</label>
            <textarea
              value={plan.summary}
              onChange={(e) => setPlan((prev) => ({ ...prev, summary: e.target.value }))}
              rows={3}
            />
          </div>

          {plan.has_tasks === false ? (
            <p className="banner-info" style={{ marginTop: 16 }}>
              <strong>No action items were found in this image.</strong>{' '}
              {plan.summary ? `Here's what we detected instead: ${plan.summary}` : ''}
            </p>
          ) : (
            <div>
              <h3>Tasks</h3>
              <table className="task-table">
                <thead>
                  <tr>
                    <th>Task</th>
                    <th>Owner</th>
                    <th>Due</th>
                    <th>Priority</th>
                    <th>Context</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {plan.tasks.map((t, i) => (
                    <tr key={i}>
                      <td>
                        <textarea
                          className="cell-textarea"
                          value={t.title}
                          onChange={(e) => updateTask(i, 'title', e.target.value)}
                          rows={2}
                        />
                      </td>
                      <td>
                        <input
                          value={t.owner}
                          onChange={(e) => updateTask(i, 'owner', e.target.value)}
                        />
                      </td>
                      <td>
                        <input
                          value={t.due}
                          onChange={(e) => updateTask(i, 'due', e.target.value)}
                        />
                      </td>
                      <td>
                        <select
                          value={t.priority}
                          onChange={(e) => updateTask(i, 'priority', e.target.value)}
                        >
                          {PRIORITIES.map((p) => (
                            <option key={p || 'none'} value={p}>
                              {p || '—'}
                            </option>
                          ))}
                        </select>
                        <span className={priorityClass(t.priority)} style={{ marginLeft: 6 }}>
                          {t.priority}
                        </span>
                      </td>
                      <td>
                        <textarea
                          className="cell-textarea"
                          value={t.context}
                          onChange={(e) => updateTask(i, 'context', e.target.value)}
                          rows={2}
                        />
                      </td>
                      <td>
                        <button className="btn btn-danger" onClick={() => removeTask(i)}>
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="btn-row">
                <button className="btn btn-secondary" onClick={addTask}>Add task</button>
              </div>
            </div>
          )}

          <h3>Open questions (editable)</h3>
          <div className="questions-box">
            {plan.open_questions.length === 0 && <p className="empty-state">None.</p>}
            {plan.open_questions.map((q, i) => (
              <div className="q-item" key={i}>
                <input value={q} onChange={(e) => updateQuestion(i, e.target.value)} />
                <button className="btn btn-danger" onClick={() => removeQuestion(i)}>Remove</button>
              </div>
            ))}
            <div className="btn-row">
              <button className="btn btn-secondary" onClick={addQuestion}>Add question</button>
            </div>
          </div>

          <hr className="divider" />
          <h3>Export</h3>
          <div className="btn-row">
            <button className="btn btn-primary" onClick={copyMarkdown}>Copy as Markdown</button>
            <button className="btn btn-secondary" onClick={downloadMarkdown}>Download as .md</button>
          </div>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}

export default App
