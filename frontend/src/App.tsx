import { Route, Routes } from "react-router-dom";
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
import { useParams } from "react-router-dom";

/** 读路由参数并以 key 重挂载做题页：bankId 切换时整套做题状态正确重置 */
function BankDrillRoute() {
  const { bankId } = useParams<{ bankId: string }>();
  return <BankDrillPage key={bankId} />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthGate />
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/mindmap" element={<MindMapListPage />} />
          <Route path="/mindmap/:mapId" element={<MindMapCanvasPage />} />
          <Route path="/courses/new" element={<NewCoursePage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/courses/:courseId" element={<CourseDetailPage />} />
          <Route path="/read/:documentId" element={<ReaderPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/wrongbook" element={<WrongBookPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/bank" element={<BankListPage />} />
          {/* bankId 变化时强制重挂载：做题草稿/轮次/错题解析等整套状态不跨题库残留 */}
          <Route
            path="/bank/:bankId"
            element={
              <BankDrillRoute />
            }
          />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<div className="p-10 text-gray-500 dark:text-gray-400">页面不存在</div>} />
        </Route>
      </Routes>
    </ErrorBoundary>
  );
}
