"use client";

import { useState } from "react";
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createStrategy } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Zap } from "lucide-react";

interface CreateStrategyDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function CreateStrategyDialog({
  open,
  onClose,
  onCreated,
}: CreateStrategyDialogProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [capital, setCapital] = useState("10000");
  const [maxPos, setMaxPos] = useState("25");
  const [maxDD, setMaxDD] = useState("10");
  const [loading, setLoading] = useState(false);
  const { addToast } = useToast();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setLoading(true);
    try {
      await createStrategy({
        name: name.trim(),
        description,
        allocated_capital: parseFloat(capital),
        max_position_pct: parseFloat(maxPos),
        max_drawdown_pct: parseFloat(maxDD),
      });
      addToast(`Strategy "${name}" created`, "success");
      onCreated();
      onClose();
      setName("");
      setDescription("");
    } catch (err: any) {
      addToast(err.message, "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose}>
      <DialogHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-blue-500/10">
            <Zap className="h-4 w-4 text-blue-400" />
          </div>
          <DialogTitle>Create Strategy</DialogTitle>
        </div>
      </DialogHeader>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="text-[10px] font-semibold uppercase tracking-wider text-white/25 mb-1.5 block">
            Name
          </label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Golden Cross BTC"
            required
          />
        </div>
        <div>
          <label className="text-[10px] font-semibold uppercase tracking-wider text-white/25 mb-1.5 block">
            Description
          </label>
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/25 mb-1.5 block">
              Capital ($)
            </label>
            <Input
              type="number"
              value={capital}
              onChange={(e) => setCapital(e.target.value)}
              min="100"
              step="100"
            />
          </div>
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/25 mb-1.5 block">
              Max Position %
            </label>
            <Input
              type="number"
              value={maxPos}
              onChange={(e) => setMaxPos(e.target.value)}
              min="1"
              max="100"
            />
          </div>
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/25 mb-1.5 block">
              Max Drawdown %
            </label>
            <Input
              type="number"
              value={maxDD}
              onChange={(e) => setMaxDD(e.target.value)}
              min="1"
              max="100"
            />
          </div>
        </div>
        <div className="flex gap-3 pt-2">
          <Button type="button" variant="outline" onClick={onClose} className="flex-1">
            Cancel
          </Button>
          <Button type="submit" disabled={loading} className="flex-1">
            {loading ? "Creating..." : "Create Strategy"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
