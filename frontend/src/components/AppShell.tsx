import { ReactNode, useEffect, useMemo, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router'
import {
  BarChart3,
  BriefcaseBusiness,
  Building2,
  BookOpenCheck,
  CalendarCheck2,
  FileText,
  LogOut,
  Menu,
  MessageSquareText,
  MoreHorizontal,
  Newspaper,
  Plus,
  Radar,
  ShieldCheck,
  X,
} from 'lucide-react'
import { useAuthStore } from '../stores/auth'
import { Button, cn } from './ui'

type NavItem = {
  to: string
  label: string
  icon: typeof BriefcaseBusiness
  matchPrefixes?: string[]
}

const navGroups: Array<{ label: string; items: NavItem[] }> = [
  {
    label: '工作台',
    items: [
      { to: '/jobs', label: '岗位工作台', icon: BriefcaseBusiness, matchPrefixes: ['/jobs'] },
    ],
  },
  {
    label: '求职资料',
    items: [
      { to: '/resumes', label: '简历资产', icon: BarChart3, matchPrefixes: ['/resumes'] },
    ],
  },
  {
    label: '面试训练',
    items: [
      { to: '/interviews/new', label: '模拟面试', icon: MessageSquareText, matchPrefixes: ['/interviews', '/reports'] },
      { to: '/training-plan', label: '训练计划', icon: CalendarCheck2 },
      { to: '/agent-questions', label: 'Agent 题库', icon: BookOpenCheck },
    ],
  },
  {
    label: '面试情报',
    items: [
      { to: '/experiences', label: '真实面经', icon: Newspaper },
      { to: '/company-profiles', label: '公司参考', icon: Radar },
    ],
  },
  {
    label: '管理设置',
    items: [
      { to: '/organizations', label: '组织管理', icon: Building2 },
      { to: '/account/security', label: '账号安全', icon: ShieldCheck },
    ],
  },
]

const allNavItems = navGroups.flatMap((group) => group.items)
const mobilePrimaryItems = [allNavItems[0], allNavItems[1], allNavItems[3], allNavItems[4]]

function isItemActive(item: NavItem, pathname: string) {
  const prefixes = item.matchPrefixes || [item.to]
  return prefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
}

function NavigationGroups({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation()
  return (
    <nav aria-label="主导航">
      {navGroups.map((group) => (
        <div key={group.label}>
          <div className="nav-section-label">{group.label}</div>
          <div className="space-y-1">
            {group.items.map((item) => {
              const Icon = item.icon
              const active = isItemActive(item, pathname)
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={onNavigate}
                  className={cn('nav-item', active && 'nav-item-active')}
                >
                  <Icon size={18} />
                  <span>{item.label}</span>
                </NavLink>
              )
            })}
          </div>
        </div>
      ))}
    </nav>
  )
}

export default function AppShell({
  title,
  description,
  actions,
  children,
  contentWidth = 'default',
}: {
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  contentWidth?: 'default' | 'wide'
}) {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  useEffect(() => {
    setMobileMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!mobileMenuOpen) return
    const previousOverflow = document.body.style.overflow
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileMenuOpen(false)
    }
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [mobileMenuOpen])

  const currentSection = useMemo(() => {
    const group = navGroups.find((item) => item.items.some((navItem) => isItemActive(navItem, location.pathname)))
    return group?.label || '工作空间'
  }, [location.pathname])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="app-bg min-h-screen">
      <header className="mobile-shell-header">
        <div className="flex min-w-0 items-center gap-3">
          <div className="brand-mark h-9 w-9">
            <span aria-hidden="true">面</span>
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-bold text-slate-950">{title}</div>
            <div className="text-xs text-slate-500">面试训练工作台</div>
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setMobileMenuOpen(true)}
          aria-label="打开全部导航"
          aria-expanded={mobileMenuOpen}
          data-testid="mobile-menu-button"
        >
          <Menu size={20} />
        </Button>
      </header>

      {mobileMenuOpen && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-40 bg-slate-950/30 lg:hidden"
            aria-label="关闭导航"
            onClick={() => setMobileMenuOpen(false)}
          />
          <aside className="mobile-nav-drawer" role="dialog" aria-modal="true" aria-label="全部导航">
            <div className="flex items-center justify-between border-b border-slate-200 pb-4">
              <div className="flex items-center gap-3">
                <div className="brand-mark h-9 w-9"><span aria-hidden="true">面</span></div>
                <div>
                  <div className="text-sm font-bold text-slate-950">面试简历</div>
                  <div className="text-xs text-slate-500">面试训练工作台</div>
                </div>
              </div>
              <Button type="button" variant="ghost" size="sm" aria-label="关闭导航" onClick={() => setMobileMenuOpen(false)} autoFocus>
                <X size={20} />
              </Button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto py-1">
              <NavigationGroups onNavigate={() => setMobileMenuOpen(false)} />
            </div>
            <div className="border-t border-slate-200 pt-4">
              <div className="mb-3 truncate px-2 text-xs text-slate-500">{user?.email}</div>
              <Button type="button" variant="ghost" className="w-full justify-start" onClick={handleLogout}>
                <LogOut size={16} />
                退出登录
              </Button>
            </div>
          </aside>
        </>
      )}

      <aside className="shell-sidebar">
        <div className="brand-block">
          <div className="brand-mark">
            <span aria-hidden="true">面</span>
          </div>
          <div className="min-w-0">
            <div className="brand-title">面试简历</div>
            <div className="brand-subtitle">面试训练工作台</div>
          </div>
        </div>

        <Button type="button" className="mt-4 w-full justify-start !border-white !bg-white !text-slate-950 hover:!bg-slate-100" onClick={() => navigate('/interviews/new')}>
          <Plus size={17} />
          开始一次面试
        </Button>

        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          <NavigationGroups />
        </div>

        <div className="sidebar-footer">
          <div className="security-note"><ShieldCheck size={15} /><span>当前组织内可见</span></div>
          <div className="user-block">
            <div className="user-avatar">
              <FileText size={16} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold text-white">
                {user?.nickname || '当前用户'}
              </div>
              <div className="truncate text-xs text-slate-500">{user?.email}</div>
            </div>
            <Button type="button" variant="ghost" size="sm" className="!text-slate-300 hover:!bg-white/10 hover:!text-white" onClick={handleLogout} aria-label="退出登录" title="退出登录">
              <LogOut size={16} />
            </Button>
          </div>
        </div>
      </aside>

      <main className="shell-main">
        <div className={cn('shell-content', contentWidth === 'wide' && 'shell-content-wide')}>
          <header className="page-header">
            <div>
              <div className="page-eyebrow">{currentSection}</div>
              <h1>{title}</h1>
              {description && <p>{description}</p>}
            </div>
            <div className="page-actions">
              {actions || (
                <Button type="button" onClick={() => navigate('/interviews/new')}>
                  <Plus size={16} />
                  创建面试
                </Button>
              )}
            </div>
          </header>
          {children}
        </div>
      </main>

      <nav className="mobile-bottom-nav" aria-label="快捷导航">
        {mobilePrimaryItems.map((item) => {
          const Icon = item.icon
          const active = isItemActive(item, location.pathname)
          return (
            <NavLink key={item.to} to={item.to} className={cn('mobile-bottom-item', active && 'mobile-bottom-item-active')}>
              <Icon />
              <span className="truncate">{item.label.replace('Agent ', '')}</span>
            </NavLink>
          )
        })}
        <button type="button" className="mobile-bottom-item" onClick={() => setMobileMenuOpen(true)} aria-label="更多导航">
          <MoreHorizontal />
          <span>更多</span>
        </button>
      </nav>
    </div>
  )
}
