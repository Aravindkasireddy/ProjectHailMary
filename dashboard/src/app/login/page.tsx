'use client';

import { Suspense, useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Lock, ChevronRight, XCircle, RefreshCw } from 'lucide-react';
import { supabase } from '../../supabaseClient';

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const mode = searchParams.get('mode') === 'register' ? 'register' : 'login';

  const [authMode, setAuthMode] = useState<'login' | 'register'>(mode);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);

  // If already authenticated, go straight to dashboard
  useEffect(() => {
    void supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) router.replace('/');
      else setChecking(false);
    });
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (authMode === 'login') {
        const { data, error: authError } = await supabase.auth.signInWithPassword({ email, password });
        if (authError) throw authError;
        if (data.session) {
          const userEmail = data.session.user.email || email;
          const role = userEmail === 'admin@hailmary.ai' ? 'admin' : 'user';
          localStorage.setItem('maas_auth_token', data.session.access_token);
          localStorage.setItem('maas_auth_role', role);
          localStorage.setItem('maas_auth_email', userEmail);
          router.replace(searchParams.get('next') || '/');
        }
      } else {
        const { error: authError } = await supabase.auth.signUp({ email, password });
        if (authError) throw authError;
        setAuthMode('login');
        setPassword('');
        setError('');
        // Show success inline — no toast available here
        setError('__success__Account created! Check your email or sign in.');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed.');
    } finally {
      setLoading(false);
    }
  };

  if (checking) return null;

  const isSuccess = error.startsWith('__success__');
  const displayError = isSuccess ? error.slice(11) : error;

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center text-slate-100 px-4 relative overflow-hidden">
      {/* Background blobs */}
      <div className="absolute top-0 left-1/4 w-96 h-96 bg-violet-600/10 rounded-full blur-[80px] pointer-events-none" />
      <div className="absolute top-1/3 right-1/4 w-96 h-96 bg-indigo-600/10 rounded-full blur-[80px] pointer-events-none" />

      <div className="w-full max-w-md bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-8 shadow-2xl relative z-10 animate-in fade-in zoom-in-95 duration-300">
        <div className="flex flex-col items-center space-y-6">

          {/* Icon + title */}
          <div className="p-4 bg-gradient-to-tr from-violet-600 to-indigo-600 rounded-2xl shadow-xl shadow-violet-500/10">
            <Lock className="w-8 h-8 text-white" />
          </div>
          <div className="text-center space-y-1">
            <h1 className="text-2xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
              MAAS Sourcing Agent
            </h1>
            <p className="text-sm text-slate-400">Master Classifier Policy Dashboard</p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="w-full space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Email Address
              </label>
              <input
                type="email"
                placeholder="name@example.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="w-full bg-slate-950/80 border border-slate-800 rounded-xl px-4 py-3 text-slate-100 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-600/50 focus:border-violet-500 transition-all"
                required
                autoComplete="email"
                autoFocus
              />
            </div>

            <div className="space-y-2">
              <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Password
              </label>
              <input
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full bg-slate-950/80 border border-slate-800 rounded-xl px-4 py-3 text-slate-100 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-600/50 focus:border-violet-500 transition-all"
                required
                autoComplete={authMode === 'login' ? 'current-password' : 'new-password'}
              />
            </div>

            {error && (
              <div className={`flex items-center space-x-2 rounded-xl p-3 text-sm animate-in duration-200 ${
                isSuccess
                  ? 'bg-emerald-950/30 border border-emerald-800/50 text-emerald-400'
                  : 'bg-rose-950/30 border border-rose-800/50 text-rose-400'
              }`}>
                <XCircle className="w-4 h-4 shrink-0" />
                <span>{displayError}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white font-semibold py-3 px-4 rounded-xl shadow-lg shadow-violet-500/20 transition-all flex items-center justify-center space-x-2 disabled:opacity-50 disabled:cursor-not-allowed group"
            >
              {loading ? (
                <RefreshCw className="w-5 h-5 animate-spin" />
              ) : (
                <>
                  <span>{authMode === 'login' ? 'Authenticate' : 'Create Account'}</span>
                  <ChevronRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                </>
              )}
            </button>

            <div className="text-center pt-2">
              <button
                type="button"
                onClick={() => {
                  const next = authMode === 'login' ? 'register' : 'login';
                  setAuthMode(next);
                  setError('');
                  router.replace(`/login${next === 'register' ? '?mode=register' : ''}`);
                }}
                className="text-xs text-violet-400 hover:text-violet-300 font-medium transition-colors"
              >
                {authMode === 'login'
                  ? "Don't have an account? Create one"
                  : 'Already have an account? Sign in'}
              </button>
            </div>
          </form>

          <p className="text-xs text-slate-500 text-center border-t border-slate-800/60 pt-4 w-full">
            Sign in with Supabase Auth. Your session is verified by the MAAS API on every request.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
