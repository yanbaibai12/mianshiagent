import { useState } from 'react'
import { useNavigate } from 'react-router'
import { ArrowRight, LockKeyhole, Mail, UserPlus } from 'lucide-react'
import { Button, Field } from '../components/ui'
import { authApi } from '../services/auth'
import { useAuthStore } from '../stores/auth'

export default function LoginPage() {
  const [isRegister, setIsRegister] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const setAuth = useAuthStore((state) => state.setAuth)

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (isRegister) {
        await authApi.register(email.trim(), password, nickname.trim() || undefined)
      }
      const res = await authApi.login(email.trim(), password)
      setAuth(res.data.access_token, res.data.user)
      navigate('/resumes')
    } catch (err: any) {
      setError(err.response?.data?.detail || '操作失败，请检查账号信息')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="flex min-h-screen flex-col bg-[#f4f5f4]">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4 sm:px-8">
        <div className="flex items-center gap-3">
          <div className="brand-mark"><span aria-hidden="true">面</span></div>
          <div>
            <div className="text-sm font-bold text-slate-950">面试简历</div>
            <div className="text-xs text-slate-500">求职准备记录</div>
          </div>
        </div>
        <div className="hidden text-xs text-slate-500 sm:block">简历 · 岗位 · 面试 · 复盘</div>
      </header>

      <section className="flex flex-1 items-center justify-center px-5 py-12 sm:px-8">
        <div className="w-full max-w-[400px]">
          <div className="mb-7">
            <h1 className="text-2xl font-bold text-slate-950">{isRegister ? '创建账号' : '登录'}</h1>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              {isRegister ? '开始整理你的简历和面试记录。' : '继续上次的求职准备。'}
            </p>
          </div>

          {error && (
            <div role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
            <Field label="邮箱">
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-2.5 text-slate-400" size={18} />
                <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} className="input pl-10" autoComplete="email" required />
              </div>
            </Field>

            <Field label="密码">
              <div className="relative">
                <LockKeyhole className="pointer-events-none absolute left-3 top-2.5 text-slate-400" size={18} />
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="input pl-10"
                  autoComplete={isRegister ? 'new-password' : 'current-password'}
                  minLength={isRegister ? 8 : undefined}
                  required
                />
              </div>
            </Field>

            {isRegister && (
              <Field label="昵称">
                <div className="relative">
                  <UserPlus className="pointer-events-none absolute left-3 top-2.5 text-slate-400" size={18} />
                  <input type="text" value={nickname} onChange={(event) => setNickname(event.target.value)} className="input pl-10" maxLength={100} />
                </div>
              </Field>
            )}

            <Button type="submit" size="lg" className="w-full" disabled={loading}>
              {loading ? '处理中...' : isRegister ? '注册并登录' : '登录'}
              {!loading && <ArrowRight size={16} />}
            </Button>
          </form>

          <div className="mt-5 text-center text-sm text-slate-500">
            <button
              type="button"
              onClick={() => {
                setIsRegister(!isRegister)
                setError('')
              }}
              className="font-semibold text-slate-800 hover:text-slate-950"
            >
              {isRegister ? '已有账号，去登录' : '没有账号，创建一个'}
            </button>
          </div>
        </div>
      </section>
    </main>
  )
}
