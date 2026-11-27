import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/layout/Layout";
import { AppProvider } from "./context/AppContext";
import { ChatProvider } from "./context/ChatContext";
import ChatPage from "./pages/ChatPage";
import DashboardPage from "./pages/DashboardPage";
import DocumentsPage from "./pages/DocumentsPage";
import LearningPage from "./pages/LearningPage";
import MemoryPage from "./pages/MemoryPage";
import ScreenPage from "./pages/ScreenPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <AppProvider>
      <ChatProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/chat" replace />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="chat/:sessionId" element={<ChatPage />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="learning" element={<LearningPage />} />
            <Route path="memory" element={<MemoryPage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="screen" element={<ScreenPage />} />
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Route>
        </Routes>
      </ChatProvider>
    </AppProvider>
  );
}
