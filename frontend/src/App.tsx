import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./features/home/HomePage";
import NewCoursePage from "./features/course-create/NewCoursePage";
import ImportPage from "./features/import-course/ImportPage";
import CourseDetailPage from "./features/course-create/CourseDetailPage";
import ReaderPage from "./features/reader/ReaderPage";
import ReviewPage from "./features/review/ReviewPage";
import FeynmanIndexPage from "./features/feynman/FeynmanIndexPage";
import FeynmanSessionPage from "./features/feynman/FeynmanSessionPage";
import DashboardPage from "./features/dashboard/DashboardPage";
import SettingsPage from "./features/settings/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/courses/new" element={<NewCoursePage />} />
        <Route path="/import" element={<ImportPage />} />
        <Route path="/courses/:courseId" element={<CourseDetailPage />} />
        <Route path="/read/:documentId" element={<ReaderPage />} />
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/feynman" element={<FeynmanIndexPage />} />
        <Route path="/feynman/:sessionId" element={<FeynmanSessionPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<div className="p-10 text-gray-500">页面不存在</div>} />
      </Route>
    </Routes>
  );
}
