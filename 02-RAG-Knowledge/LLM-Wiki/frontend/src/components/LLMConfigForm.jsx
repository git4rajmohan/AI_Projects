import { useState, useEffect } from 'react'
import useAppStore from '../store/appStore'

const PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'azure', label: 'Azure OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'ollama', label: 'Ollama (local)' },
  { value: 'lmstudio', label: 'LM Studio (local)' },
  { value: 'together', label: 'Together AI' },
  { value: 'baseten', label: 'Baseten' },
  { value: 'local-cpu', label: 'Local CPU Model' },
]

const DEFAULT_MODELS = {
  openai: 'gpt-4o',
  azure: 'gpt-4o',
  anthropic: 'claude-3-5-sonnet-20241022',
  ollama: 'llama3',
  lmstudio: 'local-model',
  together: 'meta-llama/Llama-3-70b-chat-hf',
  baseten: 'my-model',
  'local-cpu': 'gemma-2-2b-it',
}

export default function LLMConfigForm() {
  const { llmConfig, setLLMConfig, setLLMConnected } = useAppStore()
  const [form, setForm] = useState(llmConfig)
  const [hasStoredKey, setHasStoredKey] = useState(false)
  const [testStatus, setTestStatus] = useState(null) // null | 'testing' | 'ok' | 'error'
  const [testMsg, setTestMsg] = useState('')
  const [saving, setSaving] = useState(false)
  const [localModels, setLocalModels] = useState([]) // [{id, label, size, downloaded}]

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data) => {
        if (data.llm) {
          const stored = data.llm.api_key === '***'
          setHasStoredKey(stored)
          setForm({ ...data.llm, api_key: '' })
          setLLMConfig(data.llm)
          setLLMConnected(!!data.llm.is_configured)
          if (data.llm.local_models_available) {
            setLocalModels(data.llm.local_models_available)
          }
        }
      })
      .catch(() => {})
  }, [])

  const refreshLocalModels = async () => {
    try {
      const res = await fetch('/api/config/local-model/models')
      const data = await res.json()
      setLocalModels(data)
    } catch {}
  }

  const update = (key, val) => setForm((f) => ({ ...f, [key]: val }))

  const handleProviderChange = (provider) => {
    setForm((f) => ({
      ...f,
      provider,
      // Only reset the model when actually switching to a different provider.
      // Re-selecting the same provider (e.g. clicking local-cpu again) must NOT
      // wipe the currently configured model back to the default.
      model: provider === f.provider ? f.model : (DEFAULT_MODELS[provider] || ''),
    }))
    if (provider === 'local-cpu') {
      refreshLocalModels()
    }
  }

  const handleLocalModelChange = (modelId) => {
    setForm((f) => ({ ...f, model: modelId }))
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const payload = {
        ...form,
        api_key: form.api_key || (hasStoredKey ? '***' : ''),
      }
      const res = await fetch('/api/config/llm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        setLLMConfig(form)
        setTestStatus(null)
        if (form.api_key) setHasStoredKey(true)
        setLLMConnected(false)
      }
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTestStatus('testing')
    setTestMsg('')
    try {
      const payload = {
        ...form,
        api_key: form.api_key || (hasStoredKey ? '***' : ''),
      }
      const res = await fetch('/api/config/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await res.json()
      if (res.ok) {
        setTestStatus('ok')
        setTestMsg(data.message || 'Connection OK')
        setLLMConnected(true)
      } else {
        setTestStatus('error')
        setTestMsg(data.detail || 'Connection failed')
        setLLMConnected(false)
      }
    } catch (e) {
      setTestStatus('error')
      setTestMsg(String(e))
    }
  }

  const needsApiKey = ['openai', 'anthropic', 'together', 'baseten'].includes(form.provider)
  const needsBase = ['baseten'].includes(form.provider)
  const isAzure = form.provider === 'azure'
  const isLocal = ['ollama', 'lmstudio'].includes(form.provider)
  const isLocalCpu = form.provider === 'local-cpu'
  const localModelOptions =
    isLocalCpu && form.model && !localModels.some((m) => m.id === form.model)
      ? [{ id: form.model, label: form.model, size: 'configured', downloaded: true }, ...localModels]
      : localModels

  return (
    <div className="space-y-4">
      {/* Provider */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Provider
        </label>
        <select
          className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 bg-white dark:bg-gray-800 dark:text-gray-100"
          value={form.provider}
          onChange={(e) => handleProviderChange(e.target.value)}
        >
          {PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </div>

      {/* Model — dropdown for local-cpu, text input for everything else */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Model
        </label>
        {isLocalCpu ? (
          <select
            className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 bg-white dark:bg-gray-800 dark:text-gray-100"
            value={form.model || ''}
            onChange={(e) => handleLocalModelChange(e.target.value)}
          >
            {localModelOptions.length === 0 && (
              <option value="">No models downloaded yet</option>
            )}
            {localModelOptions.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label} ({m.size})
              </option>
            ))}
          </select>
        ) : (
          <input
            className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 bg-white dark:bg-gray-800 dark:text-gray-100"
            value={form.model || ''}
            onChange={(e) => update('model', e.target.value)}
            placeholder="e.g. gpt-4o"
          />
        )}
      </div>

      {/* API Key */}
      {needsApiKey && (
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            API Key
          </label>
          <input
            type="password"
            className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 bg-white dark:bg-gray-800 dark:text-gray-100"
            value={form.api_key || ''}
            onChange={(e) => update('api_key', e.target.value)}
            placeholder={hasStoredKey ? 'Stored — leave blank to keep existing' : 'sk-...'}
          />
        </div>
      )}

      {/* Azure fields */}
      {isAzure && (
        <>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Azure Endpoint
            </label>
            <input
              className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 bg-white dark:bg-gray-800 dark:text-gray-100"
              value={form.azure_endpoint || ''}
              onChange={(e) => update('azure_endpoint', e.target.value)}
              placeholder="https://myresource.openai.azure.com"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Deployment Name
            </label>
            <input
              className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 bg-white dark:bg-gray-800 dark:text-gray-100"
              value={form.azure_deployment || ''}
              onChange={(e) => update('azure_deployment', e.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              API Version
            </label>
            <input
              className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 bg-white dark:bg-gray-800 dark:text-gray-100"
              value={form.azure_api_version || '2024-02-01'}
              onChange={(e) => update('azure_api_version', e.target.value)}
            />
          </div>
        </>
      )}

      {/* Baseten base URL */}
      {needsBase && (
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            API Base URL
          </label>
          <input
            className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 bg-white dark:bg-gray-800 dark:text-gray-100"
            value={form.base_url || ''}
            onChange={(e) => update('base_url', e.target.value)}
            placeholder="https://inference.baseten.co/v1"
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            End the URL at <code className="text-gray-600 dark:text-gray-300">/v1</code> — do NOT include <code className="text-gray-600 dark:text-gray-300">/chat/completions</code> (added automatically).
          </p>
        </div>
      )}

      {/* Local provider note */}
      {isLocal && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {form.provider === 'ollama'
            ? 'Connects to http://localhost:11434/v1 — make sure Ollama is running.'
            : 'Connects to http://localhost:1234/v1 — make sure LM Studio server is running.'}
        </p>
      )}

      {/* Local CPU model info */}
      {isLocalCpu && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Runs a GGUF model locally on your CPU. No API key needed.
          Place .gguf model files in the <code>models/</code> folder next to the app to make them appear in the dropdown.
        </p>
      )}

      {/* Temperature + max_tokens */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Temperature
          </label>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 bg-white dark:bg-gray-800 dark:text-gray-100"
            value={form.temperature ?? 0.3}
            onChange={(e) => update('temperature', parseFloat(e.target.value))}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Max Tokens
          </label>
          <input
            type="number"
            step="100"
            min="256"
            className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 bg-white dark:bg-gray-800 dark:text-gray-100"
            value={form.max_tokens ?? 4000}
            onChange={(e) => update('max_tokens', parseInt(e.target.value, 10))}
          />
        </div>
      </div>

      {/* Buttons */}
      <div className="flex gap-3 items-center">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white rounded text-sm font-medium"
        >
          {saving ? 'Saving…' : 'Save Settings'}
        </button>
        <button
          onClick={handleTest}
          disabled={testStatus === 'testing'}
          className="px-4 py-2 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 rounded text-sm font-medium dark:text-gray-100"
        >
          {testStatus === 'testing' ? 'Testing…' : 'Test Connection'}
        </button>
        {testStatus === 'ok' && (
          <span className="text-green-600 text-sm">✓ {testMsg}</span>
        )}
        {testStatus === 'error' && (
          <span className="text-red-500 text-sm">✗ {testMsg}</span>
        )}
      </div>
    </div>
  )
}