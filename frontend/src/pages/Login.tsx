import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BrainCircuit, LockKeyhole, Mail, UserPlus } from 'lucide-react'
import { Button, Card, Field } from '../components/ui'
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
    <div className="app-bg flex min-h-screen items-center justify-center p-4">
      <div className="grid w-full max-w-5xl gap-6 lg:grid-cols-[1fr_420px]">
        <section className="hidden rounded-lg border border-slate-200 bg-white p-8 shadow-sm lg:block">
          <div className="flex items-center gap-3">
            <div className="brand-mark">
              <BrainCircuit size={22} />
            </div>
            <div>
              <div className="text-xl font-bold text-slate-950">面试简历 Agent</div>
              <div className="text-sm text-slate-500">Resume Interview OS</div>
            </div>
          </div>
          <div className="mt-12 max-w-xl">
            <h1 className="text-3xl font-bold leading-tight text-slate-950">
              从简历优化到模拟面试，形成可复盘的求职训练闭环
            </h1>
            <p className="mt-4 text-sm leading-7 text-slate-600">
              系统将简历结构化、结合岗位知识库生成追问题，并根据回答输出维度评分和报告。
            </p>
          </div>
          <div className="mt-10 grid grid-cols-3 gap-3 text-sm">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="font-semibold text-slate-950">RAG</div>
              <div className="mt-1 text-slate-500">岗位知识检索</div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="font-semibold text-slate-950">Report</div>
              <div className="mt-1 text-slate-500">面试复盘报告</div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="font-semibold text-slate-950">Secure</div>
              <div className="mt-1 text-slate-500">用户数据隔离</div>
            </div>
          </div>
        </section>

        <Card className="self-center p-7">
          <div className="mb-6">
            <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-md bg-cyan-700 text-white lg:hidden">
              <BrainCircuit size={22} />
            </div>
            <h2 className="text-2xl font-bold text-slate-950">{isRegister ? '创建账号' : '登录工作台'}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              {isRegister ? '注册后即可上传简历并开始训练。' : '继续管理简历、面试和报告。'}
            </p>
          </div>

          {error && (
            <div className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <Field label="邮箱">
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-2.5 text-slate-400" size={18} />
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="input pl-10"
                  autoComplete="email"
                  required
                />
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
                  required
                />
              </div>
            </Field>

            {isRegister && (
              <Field label="昵称">
                <div className="relative">
                  <UserPlus className="pointer-events-none absolute left-3 top-2.5 text-slate-400" size={18} />
                  <input
                    type="text"
                    value={nickname}
                    onChange={(event) => setNickname(event.target.value)}
                    className="input pl-10"
                    maxLength={100}
                  />
                </div>
              </Field>
            )}

            <Button type="submit" size="lg" className="w-full" disabled={loading}>
              {loading ? '处理中...' : isRegister ? '注册并登录' : '登录'}
            </Button>
          </form>

          <div className="mt-5 text-center text-sm text-slate-500">
            <button
              type="button"
              onClick={() => {
                setIsRegister(!isRegister)
                setError('')
              }}
              className="font-semibold text-cyan-700 hover:text-cyan-800"
            >
              {isRegister ? '已有账号，去登录' : '没有账号，创建一个'}
            </button>
          </div>
        </Card>
      </div>
    </div>
  )
}
