import type { UploadedFile } from '../../types'

interface Props {
  text: string
  files: UploadedFile[]
}

function IntentBubble({ text, files }: Props) {
  return (
    <div className="flex justify-end">
      <div className="max-w-2xl bg-blue-600 text-white rounded-2xl rounded-br-sm px-5 py-3 shadow">
        <p className="whitespace-pre-wrap">{text}</p>
        {files.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {files.map((f) => (
              <span key={f.filename} className="text-xs bg-blue-500/60 px-2 py-1 rounded">
                📎 {f.filename}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default IntentBubble
