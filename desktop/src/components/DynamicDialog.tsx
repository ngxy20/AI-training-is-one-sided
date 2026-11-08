import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useApp } from '../store'
import { FieldControl, Modal } from '../ui'

export function DynamicDialog() {
  const app = useApp()
  const dialog = app.dialog
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!dialog) return
    const initial: Record<string, unknown> = {}
    dialog.fields.forEach((field) => { initial[field.key] = field.default ?? '' })
    setValues(initial)
    setError('')
  }, [dialog?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const ctx = useMemo(() => ({
    pid: app.activeProject?.id || '', values, notify: app.notify, openTab: app.openTab,
    bump: app.bump, refreshTree: app.refreshTree, refreshJobs: app.refreshJobs,
    refreshProjects: app.refreshProjects, switchProject: app.switchProject,
    patch: app.patch, openDialog: app.openDialog,
  }), [app, values])

  if (!dialog) return null

  const close = () => app.patch({ dialog: null })
  const submit = async () => {
    const missing = dialog.fields.filter((field) => field.required &&
      (values[field.key] === '' || values[field.key] === undefined || values[field.key] === null))
    if (missing.length) { setError(`请填写：${missing.map((m) => m.label).join('、')}`); return }
    setBusy(true); setError('')
    try {
      const callCtx = ctx as unknown as Record<string, unknown>
      const endpoint = typeof dialog.endpoint === 'function'
        ? dialog.endpoint(values, callCtx) : dialog.endpoint
      const payload = dialog.payload ? dialog.payload(values, callCtx) : values
      const method = dialog.method || 'POST'
      const result = method === 'POST' ? await api.post(endpoint, payload)
        : method === 'PUT' ? await api.put(endpoint, payload)
          : await api.patch(endpoint, payload)
      await dialog.onDone?.(result, callCtx)
      app.notify('操作成功', 'success')
      await Promise.all([app.refreshTree(), app.refreshJobs()])
      app.bump()
      close()
    } catch (e) {
      setError((e as Error).message)
    } finally { setBusy(false) }
  }

  return <Modal title={dialog.title} description={dialog.description} onClose={close}
    footer={<>
      <button className="btn ghost" onClick={close}>取消</button>
      <button className="btn primary" onClick={submit} disabled={busy}>{busy ? '执行中…' : dialog.submitLabel || '提交'}</button>
    </>}>
    {dialog.fields.map((field) => <FieldControl key={field.key} spec={field}
      value={values[field.key]} onChange={(value) => setValues((prev) => ({ ...prev, [field.key]: value }))} />)}
    {error && <div className="small" style={{ color: 'var(--red)', marginTop: 8 }}>{error}</div>}
  </Modal>
}
