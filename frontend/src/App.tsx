import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { LoadingState } from './components/ui'
import LoginPage from './pages/Login'
import { useAuthStore } from './stores/auth'

const ResumeListPage = lazy(() => import('./pages/ResumeList'))
const ResumeDetailPage = lazy(() => import('./pages/ResumeDetail'))
const JobWorkbenchPage = lazy(() => import('./pages/JobWorkbench'))
const JobDetailPage = lazy(() => import('./pages/JobDetail'))
const NewInterviewPage = lazy(() => import('./pages/NewInterview'))
const InterviewPage = lazy(() => import('./pages/Interview'))
const ReportPage = lazy(() => import('./pages/Report'))
const AgentQuestionBankPage = lazy(() => import('./pages/AgentQuestionBank'))
const ExperienceSharesPage = lazy(() => import('./pages/ExperienceShares'))
const CompanyProfilesPage = lazy(() => import('./pages/CompanyProfiles'))
const TrainingPlanPage = lazy(() => import('./pages/TrainingPlan'))
const SystemAdminPage = lazy(() => import('./pages/SystemAdmin'))
const AccountSecurityPage = lazy(() => import('./pages/AccountSecurity'))
const OrganizationSettingsPage = lazy(() => import('./pages/OrganizationSettings'))

function PrivateRoute({ children }: { children: ReactNode }) {
  const token = useAuthStore((state) => state.token)
  return token ? <>{children}</> : <Navigate to="/login" />
}

function App() {
  return (
    <Suspense fallback={<LoadingState label="正在加载页面" />}>
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
          path="/agent-questions"
          element={
            <PrivateRoute>
              <AgentQuestionBankPage />
            </PrivateRoute>
          }
        />
        <Route
          path="/experiences"
          element={
            <PrivateRoute>
              <ExperienceSharesPage />
            </PrivateRoute>
          }
        />
        <Route
          path="/company-profiles"
          element={
            <PrivateRoute>
              <CompanyProfilesPage />
            </PrivateRoute>
          }
        />
        <Route
          path="/training-plan"
          element={
            <PrivateRoute>
              <TrainingPlanPage />
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
    </Suspense>
  )
}

export default App
