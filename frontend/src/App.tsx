import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
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

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/courses/new" element={<NewCoursePage />} />
        <Route path="/import" element={<ImportPage />} />
        <Route path="/courses/:courseId" element={<CourseDetailPage />} />
        <Route path="/read/:documentId" element={<ReaderPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/wrongbook" element={<WrongBookPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/bank" element={<BankListPage />} />
        <Route path="/bank/:bankId" element={<BankDrillPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<div className="p-10 text-gray-500 dark:text-gray-400">页面不存在</div>} />
      </Route>
    </Routes>
  );
}
