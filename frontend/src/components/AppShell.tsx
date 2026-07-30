import { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router'
import {
  BarChart3,
  BrainCircuit,
  BriefcaseBusiness,
  Building2,
  FileText,
  LogOut,
  MessageSquareText,
  PlusCircle,
  ShieldCheck,
} from 'lucide-react'
import { useAuthStore } from '../stores/auth'
import { Button, cn } from './ui'

const navItems = [
  { to: '/jobs', label: '岗位工作台', icon: BriefcaseBusiness },
  { to: '/resumes', label: '简历资产', icon: BarChart3 },
  { to: '/interviews/new', label: '创建面试', icon: MessageSquareText },
  { to: '/organizations', label: '组织管理', icon: Building2 },
  { to: '/account/security', label: '账号安全', icon: ShieldCheck },
]

export default function AppShell({
  title,
  description,
  actions,
  children,
}: {
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
}) {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="app-bg min-h-screen">
      <header className="mobile-shell-header">
        <div className="flex items-center gap-3">
          <div className="brand-mark h-9 w-9">
            <BrainCircuit size={20} />
          </div>
          <div>
            <div className="text-sm font-bold text-slate-950">面试简历 Agent</div>
            <div className="text-xs text-slate-500">Resume Interview OS</div>
          </div>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={handleLogout} aria-label="退出登录">
          <LogOut size={16} />
        </Button>
      </header>
      <nav className="mobile-nav">
        {navItems.map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => cn('mobile-nav-item', isActive && 'mobile-nav-item-active')}
            >
              <Icon size={16} />
              <span>{item.label}</span>
            </NavLink>
          )
        })}
      </nav>

      <aside className="shell-sidebar">
        <div className="brand-block">
          <div className="brand-mark">
            <BrainCircuit size={22} />
          </div>
          <div>
            <div className="brand-title">面试简历 Agent</div>
            <div className="brand-subtitle">Resume Interview OS</div>
          </div>
        </div>

        <nav className="mt-8 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => cn('nav-item', isActive && 'nav-item-active')}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </NavLink>
            )
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="security-note">
            <ShieldCheck size={16} />
            <span>数据隔离与本地 RAG 已启用</span>
          </div>
          <div className="user-block">
            <div className="user-avatar">
              <FileText size={16} />
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-slate-900">
                {user?.nickname || '当前用户'}
              </div>
              <div className="truncate text-xs text-slate-500">{user?.email}</div>
            </div>
          </div>
          <Button type="button" variant="ghost" className="w-full justify-start" onClick={handleLogout}>
            <LogOut size={16} />
            退出登录
          </Button>
        </div>
      </aside>

      <main className="shell-main">
        <header className="page-header">
          <div>
            <h1>{title}</h1>
            {description && <p>{description}</p>}
          </div>
          <div className="page-actions">
            {actions || (
              <Button type="button" onClick={() => navigate('/interviews/new')}>
                <PlusCircle size={16} />
                创建面试
              </Button>
            )}
          </div>
        </header>
        {children}
      </main>
    </div>
  )
}
