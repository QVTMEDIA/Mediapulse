import { useState, type FormEvent } from 'react';
import { Gauge } from 'lucide-react';
import { ApiError, login, register, setAuthToken } from './api/client';
import type { AuthSession } from './api/contracts';

export default function AuthScreen({ onAuthenticated }: { onAuthenticated: (session: AuthSession) => void }) {
  const [mode, setMode] = useState<'signIn' | 'register'>('signIn');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const session =
        mode === 'signIn' ? await login({ email, password }) : await register({ email, password, displayName });
      setAuthToken(session.accessToken);
      onAuthenticated(session);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the Mediapulse API.');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="brand-mark">
          <div className="brand-icon">
            <Gauge size={22} aria-hidden />
          </div>
          <div>
            <strong>Mediapulse</strong>
            <span>Media intelligence</span>
          </div>
        </div>

        <div className="auth-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'signIn'}
            className={mode === 'signIn' ? 'auth-tab active' : 'auth-tab'}
            onClick={() => {
              setMode('signIn');
              setError(null);
            }}
          >
            Sign in
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'register'}
            className={mode === 'register' ? 'auth-tab active' : 'auth-tab'}
            onClick={() => {
              setMode('register');
              setError(null);
            }}
          >
            Create account
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          {mode === 'register' && (
            <label>
              Name
              <input
                type="text"
                autoComplete="name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="Jane Analyst"
              />
            </label>
          )}
          <label>
            Email
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@agency.com"
            />
          </label>
          <label>
            Password
            <input
              type="password"
              required
              minLength={mode === 'register' ? 8 : undefined}
              autoComplete={mode === 'signIn' ? 'current-password' : 'new-password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={mode === 'register' ? 'At least 8 characters' : '••••••••'}
            />
          </label>

          {mode === 'register' && (
            <p className="field-hint">
              The first account created on a fresh deployment becomes the owner; everyone after that starts as a
              member until an owner or admin promotes them, under Settings.
            </p>
          )}

          <button type="submit" className="primary-button" disabled={isSubmitting}>
            {isSubmitting ? (mode === 'signIn' ? 'Signing in…' : 'Creating account…') : mode === 'signIn' ? 'Sign in' : 'Create account'}
          </button>
          {error && <p className="inline-error">{error}</p>}
        </form>
      </div>
    </div>
  );
}
