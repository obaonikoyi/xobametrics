import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function DeleteAccountDialog({ open, onOpenChange }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const needsPassword = user?.auth_provider !== "google";

  const close = (o) => { onOpenChange(o); if (!o) { setConfirm(""); setPassword(""); } };

  const remove = async () => {
    setBusy(true);
    try {
      await api.post("/auth/delete-account", { confirm, password: needsPassword ? password : null });
      await logout();
      toast.success("Your account and all its data have been deleted.");
      navigate("/login");
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Could not delete the account.");
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-w-md" data-testid="delete-account-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">Delete your account?</DialogTitle>
          <DialogDescription>
            This permanently deletes your account, profiles, releases, analytics, reports, uploaded files and platform
            connections, and removes XobaMetrics' YouTube access. It can't be undone.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          {needsPassword && (
            <div>
              <Label htmlFor="delete-password">Your password</Label>
              <Input id="delete-password" type="password" autoComplete="current-password" value={password}
                onChange={(e) => setPassword(e.target.value)} className="mt-1.5" />
            </div>
          )}
          <div>
            <Label htmlFor="delete-confirm">Type DELETE to confirm</Label>
            <Input id="delete-confirm" value={confirm} onChange={(e) => setConfirm(e.target.value)} className="mt-1.5" data-testid="delete-account-confirm" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => close(false)}>Cancel</Button>
          <Button variant="destructive" onClick={remove} data-testid="delete-account-button"
            disabled={busy || confirm.trim().toUpperCase() !== "DELETE" || (needsPassword && !password)}>
            {busy ? "Deleting…" : "Delete everything"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
