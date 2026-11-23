import { useEffect, useRef, useState } from 'react'
import { idError, slugify, uniqueId } from './layout.js'

function Modal({ title, onClose, children, labelledBy = 'dialog-title' }) {
  const ref = useRef(null)
  useEffect(() => {
    const previous = document.activeElement
    const first = ref.current?.querySelector('input, textarea, button')
    first?.focus()
    return () => previous?.focus?.()
  }, [])
  const onKeyDown = (event) => {
    if (event.key === 'Escape') { event.stopPropagation(); onClose() }
    if (event.key !== 'Tab') return
    // Keep keyboard focus inside the dialog.
    const items = [...ref.current.querySelectorAll('input, textarea, select, button:not(:disabled)')]
    const [first, last] = [items[0], items[items.length - 1]]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div ref={ref} className="modal" role="dialog" aria-modal="true" aria-labelledby={labelledBy} onKeyDown={onKeyDown}>
      <h2 id={labelledBy}>{title}</h2>
      {children}
    </div>
  </div>
}

export function ConfirmDialog({ title, body, confirmLabel, danger, onResult }) {
  return <Modal title={title} onClose={() => onResult(false)}>
    <div className="modal-body">{body}</div>
    <div className="modal-actions">
      <button type="button" className="btn" onClick={() => onResult(false)}>Cancel</button>
      <button type="button" className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={() => onResult(true)}>{confirmLabel}</button>
    </div>
  </Modal>
}

// Display name first; the id follows the name until the person edits it.
export function NameDialog({ title, body, note, initialName, submitLabel, takenIds, onResult }) {
  const [name, setName] = useState(initialName)
  const [id, setId] = useState(() => uniqueId(slugify(initialName), takenIds))
  const [idTouched, setIdTouched] = useState(false)
  const [tried, setTried] = useState(false)
  const nameError = name.trim() ? '' : 'A display name is required.'
  const idProblem = idError(id, takenIds)
  const submit = (event) => {
    event.preventDefault()
    setTried(true)
    if (!nameError && !idProblem) onResult({ name: name.trim(), id })
  }
  return <Modal title={title} onClose={() => onResult(null)}>
    <form onSubmit={submit} noValidate>
      {body && <p className="modal-body">{body}</p>}
      <label className="field">
        <span className="field-label">Display name</span>
        <input value={name} aria-invalid={tried && Boolean(nameError)} aria-describedby="dialog-name-error"
          onChange={(event) => {
            setName(event.target.value)
            if (!idTouched) setId(uniqueId(slugify(event.target.value), takenIds))
          }} />
        <span id="dialog-name-error" className="field-error">{tried ? nameError : ''}</span>
      </label>
      <label className="field">
        <span className="field-label">Id</span>
        <input className="mono" value={id} aria-invalid={(tried || idTouched) && Boolean(idProblem)} aria-describedby="dialog-id-help"
          onChange={(event) => { setIdTouched(true); setId(event.target.value) }} />
        <span id="dialog-id-help" className={(tried || idTouched) && idProblem ? 'field-error' : 'field-help'}>
          {(tried || idTouched) && idProblem ? idProblem : 'Used for the file name. Filled in from the display name.'}
        </span>
      </label>
      {note && <p className="modal-note">{note}</p>}
      <div className="modal-actions">
        <button type="button" className="btn" onClick={() => onResult(null)}>Cancel</button>
        <button type="submit" className="btn btn-primary">{submitLabel}</button>
      </div>
    </form>
  </Modal>
}
