import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import ViolationTypes from "./ViolationTypes";
import PermitTypes from "./PermitTypes";
import Devices from "./Devices";
import ActivityLog from "./ActivityLog";
import EnforcementSettings from "./EnforcementSettings";
import Messaging from "./Messaging";

type SettingsTab = "enforcement" | "violations" | "permit-types" | "devices" | "messaging" | "activity";

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "enforcement", label: "Enforcement" },
  { id: "violations", label: "Violation Types" },
  { id: "permit-types", label: "Permit Types" },
  { id: "devices", label: "Devices" },
  { id: "messaging", label: "Messaging" },
  { id: "activity", label: "Activity Log" },
];

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab") as SettingsTab | null;
  const [tab, setTab] = useState<SettingsTab>(tabParam && TABS.some(t => t.id === tabParam) ? tabParam : "enforcement");

  function switchTab(t: SettingsTab) {
    setTab(t);
    setSearchParams({ tab: t });
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Settings</h2>

      <div className="flex gap-1 mb-6 border-b border-gray-200">
        {TABS.map(t => (
          <button key={t.id} onClick={() => switchTab(t.id)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
              tab === t.id
                ? "bg-white border border-b-0 border-gray-200 -mb-px text-navy"
                : "text-ink-mute hover:text-ink"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "enforcement" && <EnforcementSettings />}
      {tab === "violations" && <ViolationTypes />}
      {tab === "permit-types" && <PermitTypes />}
      {tab === "devices" && <Devices />}
      {tab === "messaging" && <Messaging />}
      {tab === "activity" && <ActivityLog />}
    </div>
  );
}
