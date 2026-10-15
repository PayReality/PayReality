import { useState, type FormEvent } from "react"
import { useAuth } from "./AuthContext"
import { ApiError } from "../lib/apiClient"
import { Button, Icon } from "../components/ui"

export function LoginPage() {
  const { login } = useAuth()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await login(email, password)
    } catch (err) {
      // A real 401 from the real backend -- never a made-up message.
      if (err instanceof ApiError && err.status === 401) {
        setError("Incorrect email or password.")
      } else if (err instanceof ApiError) {
        setError(`Sign-in failed (${err.status}). Please try again.`)
      } else {
        setError("Could not reach the server. Check your connection and try again.")
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-shell">
      <div className="login-card panel">
        <div className="login-brand">
          <img src="/payreality-logo.png" alt="" className="brand-mark" />
          <span>PayReality</span>
        </div>
        <div className="eyebrow">Decision Intelligence</div>
        <h1>Sign in</h1>
        <p className="login-sub">
          Use the email and password an administrator on your team created for you.
        </p>
        <form className="form-body" onSubmit={handleSubmit}>
          <label>
            Email
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
          </label>
          {error && (
            <div className="callout login-error">
              <Icon name="lock" size={15} />
              <span>{error}</span>
            </div>
          )}
          <Button kind="primary" type="submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  )
}
