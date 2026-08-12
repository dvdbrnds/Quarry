import { useSearchParams } from "react-router-dom";
import { Tabs } from "antd";
import ActivityLog from "./ActivityLog";
import Messaging from "./Messaging";
import DataManagement from "./DataManagement";
import BrandingSettings from "./BrandingSettings";
import FeatureSettings from "./FeatureSettings";

const TABS = [
  { key: "messaging", label: "Messaging", children: <Messaging /> },
  { key: "branding", label: "Branding", children: <BrandingSettings /> },
  { key: "features", label: "Features", children: <FeatureSettings /> },
  { key: "activity", label: "Activity Log", children: <ActivityLog /> },
  { key: "data", label: "Data Management", children: <DataManagement /> },
];

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const activeKey = TABS.some(t => t.key === tabParam) ? tabParam! : "messaging";

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
