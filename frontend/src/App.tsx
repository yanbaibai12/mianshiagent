import { Routes, Route, Navigate } from 'react-router'
import { useAuthStore } from './stores/auth'
import LoginPage from './pages/Login'
import ResumeListPage from './pages/ResumeList'
import ResumeDetailPage from './pages/ResumeDetail'
import JobWorkbenchPage from './pages/JobWorkbench'
import JobDetailPage from './pages/JobDetail'
import NewInterviewPage from './pages/NewInterview'
import InterviewPage from './pages/Interview'
import ReportPage from './pages/Report'
import SystemAdminPage from './pages/SystemAdmin'
import AccountSecurityPage from './pages/AccountSecurity'
import OrganizationSettingsPage from './pages/OrganizationSettings'

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  return token ? <>{children}</> : <Navigate to="/login" />
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/jobs"
        element={
          <PrivateRoute>
            <JobWorkbenchPage />
          </PrivateRoute>
        }
      />
      <Route
        path="/jobs/:id"
        element={
          <PrivateRoute>
            <JobDetailPage />
          </PrivateRoute>
        }
      />
      <Route
        path="/resumes"
        element={
          <PrivateRoute>
            <ResumeListPage />
          </PrivateRoute>
        }
      />
      <Route
        path="/resumes/:id"
        element={
          <PrivateRoute>
            <ResumeDetailPage />
          </PrivateRoute>
        }
      />
      <Route
        path="/interviews/new"
        element={
          <PrivateRoute>
            <NewInterviewPage />
          </PrivateRoute>
        }
      />
      <Route
        path="/interviews/:id"
        element={
          <PrivateRoute>
            <InterviewPage />
          </PrivateRoute>
        }
      />
      <Route
        path="/reports/:id"
        element={
          <PrivateRoute>
            <ReportPage />
          </PrivateRoute>
        }
      />
      <Route
        path="/organizations"
        element={
          <PrivateRoute>
            <OrganizationSettingsPage />
          </PrivateRoute>
        }
      />
      <Route
        path="/account/security"
        element={
          <PrivateRoute>
            <AccountSecurityPage />
          </PrivateRoute>
        }
      />
      <Route
        path="/admin/system"
        element={
          <PrivateRoute>
            <SystemAdminPage />
          </PrivateRoute>
        }
      />
      <Route path="/" element={<Navigate to="/jobs" />} />
    </Routes>
  )
}

export default App
