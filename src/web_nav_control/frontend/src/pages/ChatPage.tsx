import { useMemo, useRef, useState } from 'react'
import { sendChatMessage } from '../api/rosApi'

type ChatMode = 'text' | 'voice'

type ChatMessage = {
  role: 'user' | 'assistant'
  text: string
  timestamp: string
  intent?: string
  actions?: { type: string; target?: string }[]
}

type SpeechRecognitionLike = {
  lang: string
  interimResults: boolean
  continuous: boolean
  start(): void
  stop(): void
  onresult: ((event: { results: ArrayLike<{ 0: { transcript: string } }> }) => void) | null
  onend: (() => void) | null
  onerror: (() => void) | null
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
}

function nowLabel() {
  return new Date().toLocaleTimeString()
}

export default function ChatPage() {
  const [mode, setMode] = useState<ChatMode>('text')
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isRecording, setIsRecording] = useState(false)
  const [status, setStatus] = useState('')
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)

  const SpeechRecognition = useMemo(() => {
    if (typeof window === 'undefined') return undefined
    return window.SpeechRecognition ?? window.webkitSpeechRecognition
  }, [])

  async function handleSend() {
    const text = input.trim()
    if (!text) return
    const userMessage = { role: 'user' as const, text, timestamp: nowLabel() }
    setMessages((prev) => [...prev, userMessage])
    setInput('')
    try {
      const res = await sendChatMessage(text, mode)
      setMessages((prev) => [...prev, {
        role: 'assistant',
        text: res.reply,
        timestamp: nowLabel(),
        intent: res.intent,
        actions: res.actions ?? [],
      }])
    } catch (err) {
      setMessages((prev) => [...prev, {
        role: 'assistant',
        text: `Chat API error: ${String(err)}`,
        timestamp: nowLabel(),
        intent: 'error',
        actions: [],
      }])
    }
  }

  function startRecording() {
    if (!SpeechRecognition) {
      setStatus('Voice input is not supported in this browser')
      return
    }
    const recognition = new SpeechRecognition()
    recognition.lang = 'zh-TW'
    recognition.interimResults = false
    recognition.continuous = false
    recognition.onresult = (event) => {
      const transcript = event.results?.[0]?.[0]?.transcript ?? ''
      if (transcript) setInput(transcript)
    }
    recognition.onend = () => setIsRecording(false)
    recognition.onerror = () => {
      setIsRecording(false)
      setStatus('Voice recognition stopped with an error')
    }
    recognitionRef.current = recognition
    recognition.start()
    setStatus('')
    setIsRecording(true)
  }

  function stopRecording() {
    recognitionRef.current?.stop()
    setIsRecording(false)
  }

  return (
    <div className="chat-page">
      <section className="chat-main">
        <h1>Chat</h1>
        <div className="chat-mode">
          <button className={mode === 'text' ? 'active' : ''} onClick={() => setMode('text')}>Text</button>
          <button className={mode === 'voice' ? 'active' : ''} onClick={() => setMode('voice')}>Voice</button>
        </div>

        <div className="chat-log">
          {messages.length === 0 && <div className="empty-chat">No messages yet.</div>}
          {messages.map((msg, index) => (
            <div key={`${msg.timestamp}-${index}`} className={`chat-message ${msg.role}`}>
              <div className="chat-meta">{msg.role} | {msg.timestamp}{msg.intent ? ` | intent: ${msg.intent}` : ''}</div>
              <div>{msg.text}</div>
              {msg.actions && msg.actions.length > 0 && (
                <pre>{JSON.stringify(msg.actions, null, 2)}</pre>
              )}
            </div>
          ))}
        </div>

        {mode === 'voice' && !SpeechRecognition && (
          <div className="warning">Voice input is not supported in this browser</div>
        )}
        {status && <div className="message">{status}</div>}

        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={mode === 'voice' ? 'Voice recognition result will appear here' : 'Type a message'}
          rows={4}
        />
        <div className="chat-actions">
          {mode === 'voice' && (
            <>
              <button disabled={!SpeechRecognition || isRecording} onClick={startRecording}>Start Recording</button>
              <button disabled={!isRecording} onClick={stopRecording}>Stop Recording</button>
            </>
          )}
          <button onClick={handleSend}>Send</button>
          <button onClick={() => setMessages([])}>Clear Chat</button>
        </div>
      </section>
    </div>
  )
}
