import { useSearchParams } from "react-router-dom";
import { Tabs } from "antd";
import ViolationTypes from "./ViolationTypes";
import Devices from "./Devices";
import ActivityLog from "./ActivityLog";
import EnforcementSettings from "./EnforcementSettings";
import Messaging from "./Messaging";
import DataManagement from "./DataManagement";
import BrandingSettings from "./BrandingSettings";
import VisitorPresets from "./VisitorPresets";

const TABS = [
  { key: "enforcement", label: "Enforcement", children: <EnforcementSettings /> },
  { key: "violations", label: "Violation Types", children: <ViolationTypes /> },
  { key: "devices", label: "Devices", children: <Devices /> },
  { key: "messaging", label: "Messaging", children: <Messaging /> },
  { key: "visitor-presets", label: "Visitor Presets", children: <VisitorPresets /> },
  { key: "branding", label: "Branding", children: <BrandingSettings /> },
  { key: "activity", label: "Activity Log", children: <ActivityLog /> },
  { key: "data", label: "Data Management", children: <DataManagement /> },
];

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const activeKey = TABS.some(t => t.key === tabParam) ? tabParam! : "enforcement";

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Settings</h2>
      <Tabs
        activeKey={activeKey}
        onChange={(key) => setSearchParams({ tab: key })}
        items={TABS}
      />
    </div>
  );
}
