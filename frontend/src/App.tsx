import { PanelLeft } from "lucide-react";
import { Sidebar } from "@/components/Sidebar";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { useChatStore } from "@/stores/chatStore";

export function App() {
  const sidebarOpen = useChatStore((s) => s.sidebarOpen);
  const toggleSidebar = useChatStore((s) => s.toggleSidebar);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      <Sidebar />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <header className="flex h-12 shrink-0 items-center gap-3 border-b px-4">
          <button
            onClick={toggleSidebar}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            title={sidebarOpen ? "收起侧栏" : "展开侧栏"}
          >
            <PanelLeft className="h-5 w-5" />
          </button>
          <h1 className="text-sm font-semibold">燃气抢险智能副驾</h1>
        </header>

        <ChatWindow />
      </div>
    </div>
  );
}
