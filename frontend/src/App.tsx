import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ClustersPage from "./pages/Clusters";
import DashboardPage from "./pages/Dashboard";
import DatasetDetailPage from "./pages/DatasetDetail";
import DatasetsPage from "./pages/Datasets";
import ExportPage from "./pages/Export";
import FailuresPage from "./pages/Failures";
import PipelinePage from "./pages/Pipeline";
import ReviewPage from "./pages/Review";
import SettingsPage from "./pages/Settings";
import TracesPage from "./pages/Traces";
import UploadPage from "./pages/Upload";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="pipeline" element={<PipelinePage />} />
        <Route path="traces" element={<TracesPage />} />
        <Route path="failures" element={<FailuresPage />} />
        <Route path="clusters" element={<ClustersPage />} />
        <Route path="datasets" element={<DatasetsPage />} />
        <Route path="datasets/:id" element={<DatasetDetailPage />} />
        <Route path="review" element={<ReviewPage />} />
        <Route path="export" element={<ExportPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<div className="text-ink-400">Page not found.</div>} />
      </Route>
    </Routes>
  );
}
