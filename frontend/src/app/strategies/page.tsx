"use client";

import { useState } from "react";
import { useStrategies } from "@/hooks/use-api";
import { updateStrategy, deleteStrategy } from "@/lib/api";
import { StrategyCard } from "@/components/strategies/strategy-card";
import { CreateStrategyDialog } from "@/components/strategies/create-strategy-dialog";
import { EditStrategyDialog } from "@/components/strategies/edit-strategy-dialog";
import { StrategyMetrics } from "@/components/strategies/strategy-metrics";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import type { Strategy } from "@/types";
import { Plus, Layers } from "lucide-react";

export default function StrategiesPage() {
  const { data: strategies, mutate } = useStrategies();
  const [showCreate, setShowCreate] = useState(false);
  const [editingStrategy, setEditingStrategy] = useState<Strategy | null>(null);
  const { addToast } = useToast();

  const handleToggle = async (id: number, status: string) => {
    try {
      await updateStrategy(id, { status } as any);
      mutate();
      addToast(`Strategy ${status}`, "success");
    } catch (err: any) {
      addToast(err.message, "error");
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this strategy and all its data?")) return;
    try {
      await deleteStrategy(id);
      mutate();
      addToast("Strategy deleted", "success");
    } catch (err: any) {
      addToast(err.message, "error");
    }
  };

  return (
    <div className="relative z-10 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 border border-amber-500/10">
            <Layers className="h-5 w-5 text-amber-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Strategies</h1>
            <p className="text-xs text-white/30 mt-0.5">
              {strategies?.length ?? 0} strategies configured
            </p>
          </div>
        </div>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4" /> New Strategy
        </Button>
      </div>

      <StrategyMetrics strategies={strategies ?? []} />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {(strategies ?? []).map((s) => (
          <StrategyCard
            key={s.id}
            strategy={s}
            onToggle={handleToggle}
            onDelete={handleDelete}
            onEdit={setEditingStrategy}
          />
        ))}
        {(strategies ?? []).length === 0 && (
          <div className="col-span-3 text-center py-16 text-white/20">
            No strategies yet. Create one to get started.
          </div>
        )}
      </div>

      <CreateStrategyDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => mutate()}
      />

      <EditStrategyDialog
        strategy={editingStrategy}
        onClose={() => setEditingStrategy(null)}
        onUpdated={() => mutate()}
      />
    </div>
  );
}
