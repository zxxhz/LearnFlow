import { Route, Routes, useLocation, Link } from "react-router-dom";
import Layout from "./components/Layout";
import ErrorBoundary from "./components/ErrorBoundary";
import AuthGate from "./components/AuthGate";
import HomePage from "./features/home/HomePage";
import NewCoursePage from "./features/course-create/NewCoursePage";
import ImportPage from "./features/import-course/ImportPage";
import CourseDetailPage from "./features/course-create/CourseDetailPage";
import ReaderPage from "./features/reader/ReaderPage";
import DashboardPage from "./features/dashboard/DashboardPage";
import SettingsPage from "./features/settings/SettingsPage";
import WrongBookPage from "./features/wrongbook/WrongBookPage";
import SearchPage from "./features/wrongbook/SearchPage";
import BankListPage from "./features/bank/BankListPage";
import BankDrillPage from "./features/bank/BankDrillPage";
import MindMapListPage from "./features/mindmap/MindMapListPage";
import MindMapCanvasPage from "./features/mindmap/MindMapCanvasPage";
import SnapSolvePage from "./features/solve/SnapSolvePage";
import { useParams } from "react-router-dom";

/** 读路由参数并以 key 重挂载做题页：bankId 切换时整套做题状态正确重置 */
function BankDrillRoute() {
  const { bankId } = useParams<{ bankId: string }>();
  return <BankDrillPage key={bankId} />;
}

/** 路由粒度错误边界（v0.5.2 体检 P1）：key 随路径变化强制重挂载，
 * 任一页面渲染崩溃后站内导航即可自救，不再瘫痪整个 Layout 外壳；全局兜底边界保留。 */
function RoutedErrorBoundary({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  return <ErrorBoundary key={location.pathname}>{children}</ErrorBoundary>;
}

/** 404 兜底：给迷路用户一个回得去的入口 */
function NotFoundRoute() {
  return (
    <div className="p-10 text-center text-gray-500 dark:text-gray-400">
      <p>页面不存在</p>
      <Link to="/" className="mt-3 inline-block text-brand-600 underline dark:text-brand-400">
        返回首页
      </Link>
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthGate />
      <Routes>
        <Route element={<Layout />}>
          <Route
            path="/"
            element={
              <RoutedErrorBoundary>
                <HomePage />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/mindmap"
            element={
              <RoutedErrorBoundary>
                <MindMapListPage />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/mindmap/:mapId"
            element={
              <RoutedErrorBoundary>
                <MindMapCanvasPage />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/courses/new"
            element={
              <RoutedErrorBoundary>
                <NewCoursePage />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/import"
            element={
              <RoutedErrorBoundary>
                <ImportPage />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/solve"
            element={
              <RoutedErrorBoundary>
                <SnapSolvePage />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/courses/:courseId"
            element={
              <RoutedErrorBoundary>
                <CourseDetailPage />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/read/:documentId"
            element={
              <RoutedErrorBoundary>
                <ReaderPage />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/dashboard"
            element={
              <RoutedErrorBoundary>
                <DashboardPage />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/wrongbook"
            element={
              <RoutedErrorBoundary>
                <WrongBookPage />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/search"
            element={
              <RoutedErrorBoundary>
                <SearchPage />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/bank"
            element={
              <RoutedErrorBoundary>
                <BankListPage />
              </RoutedErrorBoundary>
            }
          />
          {/* bankId 变化时强制重挂载：做题草稿/轮次/错题解析等整套状态不跨题库残留 */}
          <Route
            path="/bank/:bankId"
            element={
              <RoutedErrorBoundary>
                <BankDrillRoute />
              </RoutedErrorBoundary>
            }
          />
          <Route
            path="/settings"
            element={
              <RoutedErrorBoundary>
                <SettingsPage />
              </RoutedErrorBoundary>
            }
          />
          <Route path="*" element={<NotFoundRoute />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  );
}
