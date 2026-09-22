import { useEffect, useState } from "react";
import { toast } from "sonner";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import { googleSignInConfigured, startGoogleSignIn } from "@/lib/googleSignIn";
import { useTheme } from "@/context/ThemeContext";
import { useWorkspace } from "@/context/WorkspaceContext";
import { useAi } from "@/context/AiContext";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Activity, LayoutDashboard, Disc3, Zap, PlugZap, FileBarChart, Sparkles,
  Sun, Moon, ChevronDown, LogOut, Users, Check, Menu, X, KeyRound,
} from "lucide-react";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/releases", label: "Releases", icon: Disc3 },
  { to: "/race", label: "Release Race", icon: Zap },
  { to: "/connections", label: "Connections", icon: PlugZap },
  { to: "/reports", label: "Reports", icon: FileBarChart },
];

function initials(name) {
  return (name || "?").split(" ").map((s) => s[0]).slice(0, 2).join("").toUpperCase();
}

export default function AppShell({ children }) {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const { profiles, activeProfile, selectProfile, workspaces } = useWorkspace();
  const { openWith } = useAi();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [googleAvailable, setGoogleAvailable] = useState(false);

  useEffect(() => {
    googleSignInConfigured().then(setGoogleAvailable);
  }, []);

  const connectGoogle = async () => {
    try {
      await startGoogleSignIn("link");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    }
  };

  const isManager = workspaces.some((w) => w.type === "manager") || profiles.length > 1;

  const SidebarContent = () => (
    <>
      <div className="flex items-center gap-2 px-2 py-1">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Activity className="h-5 w-5" />
        </div>
        <div>
          <div className="font-display text-lg font-bold leading-none">XobaMetrics</div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Private Beta</div>
        </div>
      </div>
      <nav className="mt-8 space-y-1">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} onClick={() => setMobileOpen(false)} data-testid={`nav-${label.toLowerCase().replace(" ", "-")}`}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              }`}>
            <Icon className="h-[18px] w-[18px]" /> {label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto">
        <Button data-testid="sidebar-ask-ai" onClick={() => { openWith(); setMobileOpen(false); }} className="w-full gap-2">
          <Sparkles className="h-4 w-4" /> Ask Xoba AI
        </Button>
      </div>
    </>
  );

  return (
    <div className="xoba-grid-bg min-h-screen bg-background">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-border bg-card/50 p-4 lg:flex">
        <SidebarContent />
      </aside>

      {/* Mobile sidebar */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-border bg-card p-4">
            <button className="absolute right-3 top-3 text-muted-foreground" onClick={() => setMobileOpen(false)}><X className="h-5 w-5" /></button>
            <SidebarContent />
          </aside>
        </div>
      )}

      <div className="lg:pl-64">
        {/* Top header */}
        <header className="glass sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border px-4 sm:px-6">
          <button className="lg:hidden" onClick={() => setMobileOpen(true)} data-testid="mobile-menu-button"><Menu className="h-5 w-5" /></button>

          {/* Profile switcher */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button data-testid="workspace-switcher-trigger" className="flex items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium transition-colors hover:border-primary/40">
                <Avatar className="h-6 w-6">
                  <AvatarImage src={activeProfile?.avatar} />
                  <AvatarFallback className="text-[10px]">{initials(activeProfile?.name)}</AvatarFallback>
                </Avatar>
                <span className="max-w-[140px] truncate">{activeProfile?.name || "Select profile"}</span>
                {isManager && <span className="hidden rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary sm:inline">Manager</span>}
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-64">
              <DropdownMenuLabel className="flex items-center gap-2 text-xs"><Users className="h-3.5 w-3.5" /> Creator profiles</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {profiles.map((p) => (
                <DropdownMenuItem key={p.id} data-testid={`profile-option-${p.id}`} onClick={() => selectProfile(p)} className="flex items-center gap-2">
                  <Avatar className="h-6 w-6"><AvatarFallback className="text-[10px]">{initials(p.name)}</AvatarFallback></Avatar>
                  <div className="flex-1">
                    <div className="text-sm">{p.name}</div>
                    <div className="text-[11px] text-muted-foreground">{p.genre || p.workspace_name}</div>
                  </div>
                  {activeProfile?.id === p.id && <Check className="h-4 w-4 text-primary" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <div className="ml-auto flex items-center gap-2">
            <Button variant="outline" size="sm" className="hidden gap-2 sm:flex" data-testid="header-ask-ai" onClick={() => openWith()}>
              <Sparkles className="h-4 w-4 text-primary" /> Ask AI
            </Button>
            <Button variant="ghost" size="icon" onClick={toggle} data-testid="theme-toggle-button" aria-label="Toggle theme">
              {theme === "dark" ? <Sun className="h-[18px] w-[18px]" /> : <Moon className="h-[18px] w-[18px]" />}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button data-testid="user-menu-trigger">
                  <Avatar className="h-9 w-9 border border-border">
                    <AvatarImage src={user?.picture} />
                    <AvatarFallback className="bg-primary/15 text-primary">{initials(user?.name || user?.email)}</AvatarFallback>
                  </Avatar>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>
                  <div className="text-sm font-semibold">{user?.name}</div>
                  <div className="text-xs font-normal text-muted-foreground">{user?.email}</div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {googleAvailable && !user?.google_linked && (
                  <DropdownMenuItem data-testid="connect-google-button" onClick={connectGoogle} className="gap-2">
                    <KeyRound className="h-4 w-4" /> Connect Google sign-in
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem data-testid="logout-button" onClick={() => { logout(); navigate("/login"); }} className="gap-2 text-destructive">
                  <LogOut className="h-4 w-4" /> Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
